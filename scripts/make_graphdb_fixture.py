"""Generate tests/fixtures/graphdb_batch.json from captured scraped records.

Reads debug_output/{indiamart,justdial,tradeindia}_records.json, augments
each record with deterministic city_slug/category_slug and
lead_score/lead_score_breakdown, and adds synthetic records so that
phone-keyed cross-site merging is actually exercised by the idempotency
test (the real captures contain zero cross-record phone matches and no
TradeIndia phone/email).

Usage: python scripts/make_graphdb_fixture.py
Writes: tests/fixtures/graphdb_batch.json
"""

import json
import re
from hashlib import md5
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEBUG_OUT = ROOT / "debug_output"
OUT = ROOT / "tests" / "fixtures" / "graphdb_batch.json"

SITE_INFO = {
    "indiamart": {
        "file": "indiamart_records.json",
        "source_name": "IndiaMART",
        "source_url": "https://dir.indiamart.com",
        "category_slug": "software-development",
        "city_slug": "new-delhi",
    },
    "justdial": {
        "file": "justdial_records.json",
        "source_name": "Justdial",
        "source_url": "https://www.justdial.com",
        "category_slug": "software-development",
        "city_slug": "new-delhi",
    },
    "tradeindia": {
        "file": "tradeindia_records.json",
        "source_name": "TradeIndia",
        "source_url": "https://www.tradeindia.com",
        "category_slug": "software-development",
        "city_slug": "new-delhi",
    },
}

CITY_SLUGS = [
    "new-delhi", "mumbai", "bangalore", "pune", "hyderabad",
    "chennai", "kolkata", "ahmedabad", "jaipur", "surat",
]
CATEGORY_SLUGS = [
    "software-development", "web-design", "app-development", "it-consultancy",
    "digital-marketing", "cloud-services", "seo-services", "erp-solutions",
    "cybersecurity", "data-analytics",
]


def deterministic_attrs(company_name: str) -> tuple[str, str, int, dict]:
    """Deterministic city/category/score from the company name (stable across runs)."""
    digest = md5(company_name.encode()).hexdigest()
    idx = int(digest[:8], 16)
    city_slug = CITY_SLUGS[idx % len(CITY_SLUGS)]
    category_slug = CATEGORY_SLUGS[(idx // len(CITY_SLUGS)) % len(CATEGORY_SLUGS)]
    has_phone = True  # deterministic field-population simulation
    has_email = True
    has_website = True
    score = min(
        100,
        25 * int(has_phone) + 15 * int(has_email) + 15 * int(has_website)
        + 10 + 10,
    )
    breakdown = {
        "has_phone": int(has_phone),
        "has_email": int(has_email),
        "has_website": int(has_website),
        "multi_source": 1,
        "recency": 1,
        "icp_match": 1,
    }
    return city_slug, category_slug, score, breakdown


def augment(records: list[dict], site: str) -> list[dict]:
    info = SITE_INFO[site]
    out = []
    for rec in records:
        name = rec.get("company_name") or ""
        city_slug, category_slug, score, breakdown = deterministic_attrs(name)
        out.append({
            "company_name": name,
            "website": rec.get("website"),
            "email": rec.get("email"),
            "phone": rec.get("phone"),
            "address": rec.get("address"),
            "industry_code": rec.get("industry_code"),
            "source_url": rec.get("source_url") or info["source_url"],
            "source_name": info["source_name"],
            "city_slug": city_slug,
            "category_slug": category_slug,
            "lead_score": score,
            "lead_score_breakdown": breakdown,
        })
    return out


def main():
    records = []
    for site in SITE_INFO:
        path = DEBUG_OUT / SITE_INFO[site]["file"]
        if not path.exists():
            raise SystemExit(f"Missing capture file: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        records.extend(augment(data, site))

    # Synthetic records (C1/C2 — cross-site phone merge + TradeIndia contact data).
    # The name is NOT present in the real captures, so neither record pre-exists and
    # the second one merges by PHONE key (last-10 digits), proving cross-site keying.
    synthetic_pairs = [
        {
            "company_name": "Synthetix Digital Solutions Pvt Ltd",
            "phone": "09876543210",
            "email": "info@synthetix.in",
            "website": "https://synthetix.in",
            "source_url": "https://www.justdial.com",
            "source_name": "Justdial",
        },
        {
            "company_name": "Synthetix Digital Solutions",
            "phone": "+91 98765 43210",
            "email": "sales@synthetix.in",
            "website": None,
            "source_url": "https://dir.indiamart.com",
            "source_name": "IndiaMART",
        },
    ]
    # One TradeIndia record carrying phone+email (Phase 4 enrichment data).
    synthetic_tradeindia = {
        "company_name": "Hub It Infotech",
        "phone": "9811223344",
        "email": "contact@hubit.in",
        "website": "https://hubit.in",
        "source_url": "https://www.tradeindia.com",
        "source_name": "TradeIndia",
    }

    for rec in synthetic_pairs + [synthetic_tradeindia]:
        name = rec["company_name"]
        city_slug, category_slug, score, breakdown = deterministic_attrs(name)
        rec["city_slug"] = city_slug
        rec["category_slug"] = category_slug
        rec["lead_score"] = score
        rec["lead_score_breakdown"] = breakdown
        rec["address"] = "New Delhi"
        rec["industry_code"] = "Software Development"
        records.append(rec)

    # C1/C3 — assert the cross-site phone group exists.
    from collections import defaultdict
    by_last10 = defaultdict(set)
    for r in records:
        digits = re.sub(r"\D", "", r.get("phone") or "")
        if len(digits) >= 10:
            by_last10[digits[-10:]].add(r["source_name"])
    multi = {k: v for k, v in by_last10.items() if len(v) >= 2}
    if not multi:
        raise SystemExit("Fixture invariant violated: no phone-last-10 group spans >=2 sites")
    print(f"Fixture: {len(records)} records; cross-site phone groups: {len(multi)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
