"""Unit tests for src/graphdb.client — no live Neo4j required.

Covers: normalization table (incl. OPC), legal-suffix-only fuzzy normalization (H1),
dedup-key determinism incl. cross-site phone keying, fuzzy selection + tie-break with
stubbed candidates, primary-contact (M3), source mapping (M4/M6), review-log writer
format + pipe escaping (L3), and Q3 display-name ON CREATE semantics (M1).
"""

import json
import os
from hashlib import md5

from types import SimpleNamespace

import pytest

from src.graphdb.client import (
    Q3_MERGE_COMPANY,
    _dedup_key,
    _escape_pipe,
    _primary_contact,
    _write_fuzzy_review,
    fuzzy_normalize_company_name,
    normalize_company_name,
    source_name,
)

REAL_NAMES = [
    "Nitai Technologies (OPC) Private Limited",
    "Codetrex Infotech Pvt. Ltd.",
    "Basudeb It Solution",
    "Hub It Infotech",
    "Exclserv Solutions Llp",
    "Provaibhav Consultancy Llp",
    "Tech Guru It Solutions",
    "Presto Infosolutions Pvt Ltd",
    "Trimantra Software Solution Llp",
]


class TestNormalizeCompanyName:
    def test_strips_legal_suffixes_and_punctuation(self):
        assert normalize_company_name("Tech Solutions Pvt Ltd") == "tech"
        assert normalize_company_name("Tech Solutions Pvt. Ltd.") == "tech"

    def test_opc_suffix_removed(self):
        assert normalize_company_name("Nitai Technologies (OPC) Private Limited") == "nitai"

    def test_lowercase_and_whitespace_collapse(self):
        assert normalize_company_name("  ABC   Industries  ") == "abc"

    def test_extended_suffixes(self):
        assert normalize_company_name("XYZ Technologies Ltd") == "xyz"
        assert normalize_company_name("ABC Consulting Enterprises") == "abc consulting"
        assert normalize_company_name("Foo Corporation LLC") == "foo"

    def test_real_sample_no_collisions(self):
        normalized = [normalize_company_name(n) for n in REAL_NAMES]
        assert len(normalized) == len(set(normalized)), normalized


class TestDedupKey:
    def test_phone_is_primary_key(self):
        a = _dedup_key("Acme Pvt Ltd", "07971 671113")
        b = _dedup_key("Acme", "+91 7971 671113")
        assert a == b

    def test_cross_site_same_phone_same_key(self):
        """C1/C3 — identical phone, different name/site => same key."""
        justdial = _dedup_key("Acme Corp", "7971671113", "http://acme.in")
        indiamart = _dedup_key("Acme Private Limited", "+91-7971671113", "https://www.acme.in/")
        assert justdial == indiamart

    def test_phone_key_ignores_site(self):
        key = _dedup_key("Any Name", "9876543210")
        assert key == md5(b"phone:9876543210").hexdigest()

    def test_falls_back_to_name(self):
        a = _dedup_key("Acme", None)
        b = _dedup_key("acme", None)
        assert a == b

    def test_falls_back_to_name_plus_website(self):
        a = _dedup_key("Acme", None, "http://acme.example.com")
        b = _dedup_key("Acme", None, "https://acme.example.com/")
        assert a == b


class TestFuzzyResolution:
    def _session(self, candidates):
        """Stub session.run returning candidate rows for Q2_FUZZY_SCAN."""
        class Session:
            def run(self, query, params=None):
                assert "$prefix" in query or "STARTS WITH" in query
                for c in candidates:
                    yield {
                        "dk": c["dk"],
                        "name": c["name"],
                        "norm": c["norm"],
                    }
        return Session()

    def test_highest_above_threshold_wins(self, tmp_path, monkeypatch):
        from src.graphdb.client import _resolve
        monkeypatch.chdir(tmp_path)
        cands = [
            {"dk": "dk-a", "name": "Hub It Infotech", "norm": "hub it infotech"},
            {"dk": "dk-b", "name": "Hub It Solutions Ltd", "norm": "hub it solutions"},
            {"dk": "dk-c", "name": "Hublot Watches", "norm": "hublot watches"},
        ]
        rec = {"company_name": "Hub It Infotech Pvt. Ltd."}
        res = _resolve(self._session(cands), rec, "hub it infotech", 90)
        assert res["match_type"] == "fuzzy"
        assert res["dk"] == "dk-a"

    def test_below_threshold_does_not_merge_but_is_logged(self, tmp_path, monkeypatch):
        from src.graphdb.client import _resolve
        monkeypatch.chdir(tmp_path)
        cands = [{"dk": "dk-x", "name": "Basudeb It Solution", "norm": "basudeb it solution"}]
        rec = {"company_name": "Riverside Cafe"}
        res = _resolve(self._session(cands), rec, "riverside cafe", 90)
        assert res["match_type"] is None
        log_path = tmp_path / "debug_output" / "fuzzy_matches.log"
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert "not_matched" in content

    def test_tie_break_lexicographic(self, tmp_path, monkeypatch):
        from src.graphdb.client import _resolve
        monkeypatch.chdir(tmp_path)
        # Both candidates fuzzy-normalize to "tech" and score 100.0 against
        # incoming "Tech"; tie is broken by lexicographically smaller name.
        cands = [
            {"dk": "dk-z", "name": "Tech Pvt Ltd", "norm": "tech"},
            {"dk": "dk-a", "name": "Tech Limited", "norm": "tech"},
        ]
        rec = {"company_name": "Tech"}
        res = _resolve(self._session(cands), rec, "tech", 90)
        assert res["dk"] == "dk-a"

    def test_phone_match_skips_fuzzy(self, tmp_path, monkeypatch):
        from src.graphdb.client import _resolve
        monkeypatch.chdir(tmp_path)

        class Session:
            def run(self, query, params=None):
                if "STARTS WITH" in query:
                    assert False, "fuzzy pass must be skipped for a phone match"
                return SimpleNamespace(single=lambda: {"dk": "dk-phone", "name": "Acme"})

        rec = {"company_name": "Acme Corp", "phone": "+91-7971-671113"}
        res = _resolve(Session(), rec, "acme", 90)
        assert res["match_type"] == "phone"
        assert res["dk"] == "dk-phone"


class TestFuzzyNormalizeCompanyName:
    """H1 — fuzzy normalization strips only legal suffixes, never descriptors."""

    def test_keeps_descriptor_words(self):
        assert fuzzy_normalize_company_name("Pinnacle It Solutions") == "pinnacle it solutions"
        assert fuzzy_normalize_company_name("Pinnacle It Services") == "pinnacle it services"

    def test_strips_legal_suffixes_only(self):
        assert fuzzy_normalize_company_name("Codetrex Infotech Pvt. Ltd.") == "codetrex infotech"
        assert fuzzy_normalize_company_name("Nitai Technologies (OPC) Private Limited") == "nitai technologies"

    def test_descriptor_pairs_score_below_threshold(self):
        """H1 — 'Solutions' vs 'Services' vs 'Systems' must NOT fuse at 90."""
        from rapidfuzz import fuzz
        pairs = [
            ("Pinnacle It Solutions", "Pinnacle It Services"),
            ("Tech Solutions India", "Tech Services India"),
            ("Tech Solutions India", "Tech Systems India"),
            ("Acme Technologies", "Acme Tech"),
        ]
        for a, b in pairs:
            score = fuzz.token_sort_ratio(
                fuzzy_normalize_company_name(a),
                fuzzy_normalize_company_name(b),
            )
            assert score < 90, f"{a!r} vs {b!r} scored {score:.1f} — must stay below 90"

    def test_legal_variants_score_100(self):
        """Legal-suffix variants of the same company must still merge at 100."""
        from rapidfuzz import fuzz
        pairs = [
            ("Codetrex Infotech Pvt. Ltd.", "Codetrex Infotech"),
            ("Nitai Technologies (OPC) Private Limited", "Nitai Technologies"),
        ]
        for a, b in pairs:
            score = fuzz.token_sort_ratio(
                fuzzy_normalize_company_name(a),
                fuzzy_normalize_company_name(b),
            )
            assert score == 100.0, f"{a!r} vs {b!r} scored {score:.1f} — expected 100"

    def test_resolve_does_not_merge_descriptor_pairs(self, tmp_path, monkeypatch):
        """H1 end-to-end — over-normalization no longer fuses distinct companies."""
        from src.graphdb.client import _resolve
        monkeypatch.chdir(tmp_path)

        class Session:
            def run(self, query, params=None):
                yield {"dk": "dk-sol", "name": "Pinnacle It Solutions", "norm": "pinnacle it solutions"}

        rec = {"company_name": "Pinnacle It Services"}
        res = _resolve(Session(), rec, "pinnacle it", 90)
        assert res["match_type"] is None
        assert res["dk"] != "dk-sol"


class TestPrimaryContact:
    """M3 — raw_record_id primary contact is digits-only for phones."""

    def test_phone_reduced_to_digits(self):
        assert _primary_contact("+91 7971-671 113", None, None) == "917971671113"

    def test_prefers_phone_over_email_over_website(self):
        assert _primary_contact("07971 671113", "a@b.com", "http://x.in") == "07971671113"
        assert _primary_contact(None, "a@b.com", "http://x.in") == "a@b.com"
        assert _primary_contact(None, None, "http://x.in") == "http://x.in"

    def test_empty_when_nothing(self):
        assert _primary_contact(None, None, None) == ""


class TestSourceName:
    """M4/M6 — single source mapping; unknown sources resolve to None."""

    def test_known_domains(self):
        assert source_name("https://www.justdial.com/foo") == "Justdial"
        assert source_name("https://dir.indiamart.com/foo") == "IndiaMART"
        assert source_name("http://www.tradeindia.com/foo") == "TradeIndia"

    def test_unknown_returns_none(self):
        assert source_name("https://example.com") is None
        assert source_name(None) is None


class TestEscapePipe:
    """L3 — review-log field escaping per contract (\\|)."""

    def test_escapes_pipe(self):
        assert _escape_pipe("A|B") == "A\\|B"
        assert _escape_pipe("Plain") == "Plain"
        assert _escape_pipe(None) == ""


class TestMergeQuery:
    """M1 — display-name fields must only be written ON CREATE."""

    def test_company_name_only_on_create(self):
        on_create = Q3_MERGE_COMPANY.split("ON MATCH SET")[0]
        assert "c.company_name = $name" in on_create
        assert "c.normalized_name = $norm" in on_create
        on_match = Q3_MERGE_COMPANY.split("ON MATCH SET")[1]
        assert "c.company_name" not in on_match
        assert "c.normalized_name" not in on_match

    def test_first_seen_only_on_create(self):
        on_create = Q3_MERGE_COMPANY.split("ON MATCH SET")[0]
        assert "c.first_seen = $now" in on_create
        on_match = Q3_MERGE_COMPANY.split("ON MATCH SET")[1]
        assert "first_seen" not in on_match


class TestReviewLogWriter:
    def test_header_and_line_format(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_fuzzy_review(
            incoming="Codetrex Infotech Pvt. Ltd.", incoming_norm="codetrex infotech",
            candidate="Codetrex Infotech", candidate_norm="codetrex infotech",
            score=100.0, threshold=90, verdict="matched",
        )
        path = tmp_path / "debug_output" / "fuzzy_matches.log"
        content = path.read_text(encoding="utf-8")
        lines = content.strip().splitlines()
        assert lines[0] == "timestamp|action|incoming_name|incoming_normalized|candidate_name|candidate_normalized|score|threshold|verdict"
        assert "FUZZY_MATCH" in lines[1]
        assert "codetrex infotech" in lines[1]
        assert "100.0|90|matched" in lines[1]

    def test_below_threshold_verdict_not_matched(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_fuzzy_review(
            incoming="A", incoming_norm="a",
            candidate="B", candidate_norm="b",
            score=40.0, threshold=90, verdict="not_matched",
        )
        content = (tmp_path / "debug_output" / "fuzzy_matches.log").read_text(encoding="utf-8")
        assert "40.0|90|not_matched" in content

    def test_append_does_not_duplicate_header(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for _ in range(2):
            _write_fuzzy_review(
                incoming="A", incoming_norm="a",
                candidate="B", candidate_norm="b",
                score=50.0, threshold=90, verdict="not_matched",
            )
        content = (tmp_path / "debug_output" / "fuzzy_matches.log").read_text(encoding="utf-8")
        assert content.count("timestamp|action|incoming_name") == 1
        assert len(content.strip().splitlines()) == 3  # header + 2 lines
