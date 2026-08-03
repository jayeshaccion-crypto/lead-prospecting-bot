"""High-level Neo4j graph API with entity resolution for the lead prospecting pipeline."""

import json
import logging
import os
import re
import sys
import threading
import unicodedata
from datetime import datetime, timezone
from hashlib import md5

from neo4j import GraphDatabase
from rapidfuzz import fuzz

from .schema import create_schema

logger = logging.getLogger(__name__)

SITE_SOURCES = {
    "justdial.com": "Justdial",
    "indiamart.com": "IndiaMART",
    "tradeindia.com": "TradeIndia",
}


def normalize_company_name(name: str) -> str:
    """Normalize a company name for entity resolution.

    Lowercase, strip punctuation, remove legal/corporate suffixes (Pvt, Ltd,
    LLP, Private Limited, OPC, Inc, LLC, etc.), collapse whitespace.
    Punctuation is stripped before suffix removal so 'Pvt. Ltd.', '(OPC)',
    and 'Private Limited' all normalize correctly.
    """
    n = name.lower().strip()
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(
        r"\b(pvt|ltd|llp|private\s*limited|opc|inc|corp|corporation|llc|limited|co|company|technologies|solutions|services|systems|group|industries|enterprises?)\b",
        " ", n, flags=re.IGNORECASE,
    )
    n = re.sub(r"\s+", " ", n).strip()
    return n


# Legal suffixes ONLY — business-descriptor words (solutions/services/technologies,
# etc.) are intentionally NOT stripped here so genuinely distinct companies that
# differ only by a descriptor are not fused by over-normalization (H1).
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(pvt|ltd|llp|private\s*limited|opc|inc|corp|corporation|llc|limited|co|company)\b",
    flags=re.IGNORECASE,
)


def fuzzy_normalize_company_name(name: str) -> str:
    """Normalize a name for fuzzy comparison: strip ONLY legal/corporate suffixes.

    Unlike :func:`normalize_company_name`, descriptor words such as solutions,
    services, technologies, systems, group, industries, enterprises are KEPT.
    Two genuinely different companies like 'Pinnacle It Solutions' and
    'Pinnacle It Services' therefore score well below threshold and do not merge.
    """
    n = name.lower().strip()
    n = re.sub(r"[^\w\s]", " ", n)
    n = _LEGAL_SUFFIX_RE.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _dedup_key(company_name: str, phone: str | None = None, website: str | None = None) -> str:
    """Generate a deterministic dedup key.

    Phone is the strongest signal — use it as primary key when available.
    Otherwise fall back to normalized name + website.
    """
    raw = ""
    if phone:
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 10:
            raw = f"phone:{digits[-10:]}"
    if not raw:
        n = normalize_company_name(company_name)
        w = (website or "").lower().strip()
        w = re.sub(r"^https?://", "", w).rstrip("/")
        raw = f"name:{n}|web:{w}" if w else f"name:{n}"
    return md5(raw.encode()).hexdigest()


def source_name(url: str | None) -> str | None:
    """Return the canonical directory name for a source URL, or None if unknown.

    This is the single source of truth for URL → directory-name mapping (M4).
    Returning None (not a sentinel string) is what keeps unknown sources from
    ever being appended to a node's ``sources`` list or creating a SOURCED_FROM
    edge (M6).
    """
    if not url:
        return None
    for domain, name in SITE_SOURCES.items():
        if domain in url:
            return name
    return None


def ensure_schema(driver: GraphDatabase.driver):
    create_schema(driver)


_REVIEW_LOG_LOCK = threading.Lock()


def _escape_pipe(value: str) -> str:
    """Escape pipe separators as ``\\|`` per review-log-format.md contract (L3)."""
    return (value or "").replace("|", "\\|")


def _locked_append(path: str, text: str):
    """Append ``text`` to ``path`` under an advisory lock (in-process + best-effort cross-process).

    If the OS lock mechanism is unavailable (e.g. an exotic platform), falls
    back to a plain append. A genuine write error still propagates as OSError
    so callers can warn — the review log must never silently vanish (L3).
    """
    with _REVIEW_LOG_LOCK:
        lock_path = path + ".lock"
        try:
            with open(lock_path, "ab") as lf:
                if sys.platform == "win32":
                    import msvcrt
                    lf.seek(0)
                    msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(text)
                    f.flush()
        except (OSError, ImportError):
            # Lock unavailable/unsupported — plain append still works; the
            # final write can still raise OSError, which callers handle.
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)
                f.flush()


def _write_fuzzy_review(
    incoming: str,
    incoming_norm: str,
    candidate: str,
    candidate_norm: str,
    score: float,
    threshold: int,
    verdict: str,
):
    """Append a fuzzy-comparison line to debug_output/fuzzy_matches.log.

    Every fuzzy comparison is logged (matched or not). Format:
    timestamp|action|incoming_name|incoming_normalized|candidate_name|
    candidate_normalized|score|threshold|verdict
    A literal ``|`` inside a name is escaped as ``\\|`` (L3).
    """
    log_dir = "debug_output"
    path = os.path.join(log_dir, "fuzzy_matches.log")
    try:
        os.makedirs(log_dir, exist_ok=True)
        is_new = not os.path.exists(path)
        ts = datetime.now(timezone.utc).isoformat()
        line = "|".join([
            ts, "FUZZY_MATCH",
            _escape_pipe(incoming),
            _escape_pipe(incoming_norm),
            _escape_pipe(candidate),
            _escape_pipe(candidate_norm),
            f"{float(score):.1f}",
            str(int(threshold)),
            verdict,
        ])
        if is_new:
            _locked_append(
                path,
                "timestamp|action|incoming_name|incoming_normalized|"
                "candidate_name|candidate_normalized|score|threshold|verdict\n",
            )
        _locked_append(path, line + "\n")
    except OSError:
        logger.warning("Could not write fuzzy-match review log (falling back to console-only)")


Q1_PHONE_MATCH = (
    "MATCH (c:Company) WHERE c.dedup_key = $phone_dk "
    "RETURN c.dedup_key AS dk, c.company_name AS name"
)
Q2_FUZZY_SCAN = (
    "MATCH (c:Company) WHERE c.normalized_name STARTS WITH $prefix "
    "RETURN c.dedup_key AS dk, c.company_name AS name, c.normalized_name AS norm"
)
Q3_MERGE_COMPANY = """
MERGE (c:Company {dedup_key: $dk})
ON CREATE SET
  c.company_name = $name,
  c.normalized_name = $norm,
  c.phone = $phone,
  c.email = $email,
  c.website = $website,
  c.address = $address,
  c.industry_code = $industry_code,
  c.first_seen = $now,
  c.last_seen = $now,
  c.lead_score = $score,
  c.lead_score_breakdown = $breakdown,
  c.sources = $sources
ON MATCH SET
  c.phone = CASE WHEN $phone IS NOT NULL AND $phone <> '' THEN $phone ELSE c.phone END,
  c.email = CASE WHEN $email IS NOT NULL AND $email <> '' THEN $email ELSE c.email END,
  c.website = CASE WHEN $website IS NOT NULL AND $website <> '' THEN $website ELSE c.website END,
  c.address = CASE WHEN $address IS NOT NULL AND $address <> '' THEN $address ELSE c.address END,
  c.industry_code = CASE WHEN $industry_code IS NOT NULL AND $industry_code <> '' THEN $industry_code ELSE c.industry_code END,
  c.last_seen = $now,
  c.lead_score = $score,
  c.lead_score_breakdown = $breakdown,
  c.sources = CASE
    WHEN $src_name IS NOT NULL AND NOT $src_name IN COALESCE(c.sources, [])
    THEN COALESCE(c.sources, []) + [$src_name]
    ELSE c.sources
  END
"""
Q4_LISTED_IN = (
    "MATCH (c:Company {dedup_key: $dk}) "
    "MERGE (cat:Category {name: $category}) "
    "MERGE (c)-[:LISTED_IN]->(cat)"
)
Q5_LOCATED_IN = (
    "MATCH (c:Company {dedup_key: $dk}) "
    "MERGE (city:City {name: $city}) "
    "MERGE (c)-[:LOCATED_IN]->(city)"
)
Q6_SOURCED_FROM = (
    "MATCH (c:Company {dedup_key: $dk}) "
    "MERGE (s:Source {name: $source}) "
    "MERGE (c)-[r:SOURCED_FROM]->(s) "
    "SET r.scraped_at = $now, r.raw_record_id = $raw_record_id"
)


def _resolve(tx, record: dict, norm: str, threshold: int) -> dict:
    """Run entity resolution for one record against a session or transaction.

    Returns a dict: dk (the identity key to write under), match_type
    ('phone'|'fuzzy'|None), matched_name (optional), fuzzy_score (optional).
    """
    phone = (record.get("phone") or "").strip() or None

    # 1. Deterministic phone match (primary key)
    if phone:
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 10:
            row = tx.run(Q1_PHONE_MATCH, {"phone_dk": _dedup_key(record["company_name"], phone)}).single()
            if row:
                return {"dk": row["dk"], "match_type": "phone", "matched_name": row["name"]}

    # 2. Fuzzy name pass (only when no phone match)
    prefix = norm[:3] if len(norm) >= 3 else norm
    fuzzy_incoming = fuzzy_normalize_company_name(record["company_name"])
    best = None  # (score, candidate_name, dk)
    for row in tx.run(Q2_FUZZY_SCAN, {"prefix": prefix}):
        cand_name = row["name"] or ""
        cand_norm = row["norm"] or normalize_company_name(cand_name)
        # Score on legal-suffix-only normalization (H1) so descriptor-word
        # differences (Solutions vs Services) are not erased.
        score = float(fuzz.token_sort_ratio(fuzzy_incoming, fuzzy_normalize_company_name(cand_name)))
        verdict = "matched" if score >= float(threshold) else "not_matched"
        _write_fuzzy_review(
            incoming=record["company_name"], incoming_norm=norm,
            candidate=cand_name, candidate_norm=cand_norm,
            score=score, threshold=threshold, verdict=verdict,
        )
        if score >= float(threshold):
            if best is None or score > best[0] or (score == best[0] and (cand_name or "") < best[1]):
                best = (score, cand_name, row["dk"])
    if best:
        logger.info(
            "Entity resolution: fuzzy match '%s' -> '%s' (score=%.1f)",
            record["company_name"], best[1], best[0],
        )
        return {"dk": best[2], "match_type": "fuzzy", "matched_name": best[1], "fuzzy_score": best[0]}
    return {"dk": _dedup_key(record["company_name"], phone, record.get("website")), "match_type": None}


def _upsert_company_in_tx(tx, record: dict, threshold: int) -> dict:
    """Run entity resolution + all four write queries inside one transaction.

    Q3–Q6 run in a single Neo4j transaction (L6) so a partial failure rolls
    back the whole record instead of leaving a half-merged node.
    """
    company_name = (record.get("company_name") or "").strip() or "Unknown"
    phone = (record.get("phone") or "").strip() or None
    email = (record.get("email") or "").strip() or None
    website = (record.get("website") or "").strip() or None
    address = (record.get("address") or "").strip() or None
    industry_code = (record.get("industry_code") or "").strip() or None
    source_url = (record.get("source_url") or "").strip() or None
    city_slug = (record.get("city_slug") or "").strip() or None
    category_slug = (record.get("category_slug") or "").strip() or None
    lead_score = record.get("lead_score")
    lead_score_breakdown = record.get("lead_score_breakdown")
    normalized_name = normalize_company_name(company_name)
    src_name = source_name(source_url)
    now_str = datetime.now(timezone.utc).isoformat()

    resolved = _resolve(tx, record, normalized_name, threshold)
    dk = resolved["dk"]
    match_type = resolved["match_type"]

    sources = [src_name] if src_name else []
    tx.run(
        Q3_MERGE_COMPANY,
        {"dk": dk, "name": company_name, "norm": normalized_name,
         "phone": phone, "email": email, "website": website,
         "address": address, "industry_code": industry_code,
         "now": now_str, "sources": sources, "src_name": src_name,
         "score": lead_score,
         "breakdown": json.dumps(lead_score_breakdown) if lead_score_breakdown else None},
    )

    if category_slug:
        tx.run(Q4_LISTED_IN, {"dk": dk, "category": category_slug})
    if city_slug:
        tx.run(Q5_LOCATED_IN, {"dk": dk, "city": city_slug})
    if src_name:
        # M3: raw_record_id is generated here (phone digits only) so the
        # contract format is owned in one place, never raw with spaces/+.
        primary = _primary_contact(phone, email, website)
        raw_record_id = f"{src_name}|{company_name}|{primary}".lower()
        tx.run(
            Q6_SOURCED_FROM,
            {"dk": dk, "source": src_name, "now": now_str,
             "raw_record_id": raw_record_id},
        )

    result = {"dedup_key": dk, "action": "merged" if match_type else "created", "match_type": match_type}
    if resolved.get("matched_name"):
        result["matched_name"] = resolved["matched_name"]
    if resolved.get("fuzzy_score") is not None:
        result["fuzzy_score"] = resolved["fuzzy_score"]
    return result


def upsert_company(driver: GraphDatabase.driver, record: dict, threshold: int = 90) -> dict:
    """MERGE a Company node with entity resolution, return the operation result.

    Entity resolution:
    1. Deterministic phone match (last 10 digits) — phone is the primary key.
    2. If no phone match, fuzzy name match on token_sort_ratio >= threshold;
       every comparison is written to the review log.
    3. On match: MERGE the existing node (sources appended, last_seen updated).
    4. On no match: MERGE creates a new node with first_seen set once.

    Returns dict with keys: action (created/merged), dedup_key,
    match_type (phone/fuzzy/none), matched_name (if any), fuzzy_score (if any).
    """
    with driver.session() as session:
        return session.execute_write(_upsert_company_in_tx, record, threshold)


def _primary_contact(phone: str | None, email: str | None, website: str | None) -> str:
    """Return the primary contact for raw_record_id (phone > email > website).

    Phone is reduced to digits per contract (graph-schema.md §Relationship).
    """
    if phone:
        digits = re.sub(r"\D", "", phone)
        if digits:
            return digits
    if email:
        return " ".join(email.split())
    if website:
        return " ".join(website.split())
    return ""


def write_companies(driver: GraphDatabase.driver, records: list[dict], threshold: int = 90) -> dict:
    """Write multiple records to Neo4j with entity resolution.

    A single Neo4j session is reused across all records (L2); each record's
    writes are committed atomically in its own transaction (L6).

    Returns aggregate stats: created, merged (phone vs fuzzy), and total graph
    size (node + relationship counts).
    """
    stats = {"created": 0, "merged_phone": 0, "merged_fuzzy": 0}
    with driver.session() as session:
        for rec in records:
            r = session.execute_write(_upsert_company_in_tx, rec, threshold)
            if r["action"] == "created":
                stats["created"] += 1
            elif r.get("match_type") == "phone":
                stats["merged_phone"] += 1
            elif r.get("match_type") == "fuzzy":
                stats["merged_fuzzy"] += 1
    stats["graph"] = get_stats(driver)
    return stats


def query_by_location(driver: GraphDatabase.driver, city: str):
    with driver.session() as session:
        result = session.run(
            """MATCH (c:Company)-[:LOCATED_IN]->(city:City {name: $city})
               OPTIONAL MATCH (c)-[:LISTED_IN]->(cat:Category)
               OPTIONAL MATCH (c)-[:SOURCED_FROM]->(s:Source)
               RETURN c.company_name AS company_name,
                      c.website AS website,
                      c.address AS address,
                      c.phone AS phone,
                      c.email AS email,
                      c.lead_score AS lead_score,
                      collect(DISTINCT cat.name) AS categories,
                      collect(DISTINCT s.name) AS sources
               ORDER BY c.company_name""",
            {"city": city},
        )
        return list(result)


def query_company_detail(driver: GraphDatabase.driver, company_name: str):
    with driver.session() as session:
        result = session.run(
            """MATCH (c:Company)
               WHERE toLower(c.company_name) CONTAINS toLower($name)
               OPTIONAL MATCH (c)-[:LOCATED_IN]->(city:City)
               OPTIONAL MATCH (c)-[:LISTED_IN]->(cat:Category)
               OPTIONAL MATCH (c)-[:SOURCED_FROM]->(s:Source)
               RETURN c.company_name AS company_name,
                      c.website AS website,
                      c.address AS address,
                      c.phone AS phone,
                      c.email AS email,
                      city.name AS city,
                      collect(DISTINCT cat.name) AS categories,
                      collect(DISTINCT s.name) AS sources,
                      c.lead_score AS lead_score,
                      c.lead_score_breakdown AS lead_score_breakdown
               ORDER BY c.company_name""",
            {"name": company_name},
        )
        return list(result)


def get_company_count(driver: GraphDatabase.driver) -> int:
    with driver.session() as session:
        result = session.run("MATCH (c:Company) RETURN count(c) AS cnt")
        return result.single()["cnt"]


def get_stats(driver: GraphDatabase.driver) -> dict[str, int]:
    with driver.session() as session:
        stats = {}
        for label in ("Company", "Category", "City", "Source"):
            result = session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt")
            stats[label] = result.single()["cnt"]
        # Relationship counts
        for rel in ("LISTED_IN", "LOCATED_IN", "SOURCED_FROM"):
            result = session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS cnt")
            stats[rel] = result.single()["cnt"]
        return stats
