from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.models import LeadRecord, RejectedDuplicate
from src.pipeline import (
    _enrichment_field_count,
    deduplicate_records,
    record_to_row,
    rejected_to_row,
    write_rejected_duplicates,
)
from src.database.client import DEDUP_KEY_INDEX, filter_new_rows
from src.database.tabs import LEADS_HEADERS


TIP = datetime(2025, 1, 1, tzinfo=timezone.utc)


def make_record(company: str, dedup_key: str | None, **kw) -> LeadRecord:
    return LeadRecord(
        company_name=company,
        dedup_key=dedup_key,
        scraped_at=TIP,
        **kw,
    )


class TestEnrichmentFieldCount:
    def test_both_none(self):
        r = make_record("A", "key")
        assert _enrichment_field_count(r) == 0

    def test_employee_only(self):
        r = make_record("A", "key", employee_count=50)
        assert _enrichment_field_count(r) == 1

    def test_revenue_only(self):
        r = make_record("A", "key", revenue_band="$10M-$50M")
        assert _enrichment_field_count(r) == 1

    def test_both_set(self):
        r = make_record("A", "key", employee_count=50, revenue_band="$10M-$50M")
        assert _enrichment_field_count(r) == 2


class TestDeduplicateRecords:
    def test_no_duplicates_all_kept(self):
        records = [
            make_record("Alpha", "a.com"),
            make_record("Beta", "b.com"),
        ]
        kept, rejected = deduplicate_records(records)
        assert len(kept) == 2
        assert len(rejected) == 0

    def test_keeps_richer_when_collision(self):
        records = [
            make_record("Alpha", "same-key", employee_count=100),
            make_record("Beta", "same-key"),
        ]
        kept, rejected = deduplicate_records(records)
        assert len(kept) == 1
        assert kept[0].company_name == "Alpha"
        assert len(rejected) == 1
        assert rejected[0].dedup_key == "same-key"
        assert rejected[0].kept_company == "Alpha"
        assert rejected[0].rejected_company == "Beta"
        assert rejected[0].timestamp is not None

    def test_tie_goes_to_alphabetically_first(self):
        records = [
            make_record("Beta", "same-key", employee_count=50),
            make_record("Alpha", "same-key", revenue_band="$10M"),
        ]
        kept, rejected = deduplicate_records(records)
        assert len(kept) == 1
        assert kept[0].company_name == "Alpha"
        assert len(rejected) == 1
        assert rejected[0].rejected_company == "Beta"
        assert "Tied at" in rejected[0].reason

    def test_multiple_collisions(self):
        records = [
            make_record("Alpha", "k1", employee_count=100),
            make_record("Beta", "k1"),
            make_record("Gamma", "k2"),
            make_record("Delta", "k2", revenue_band="$50M"),
        ]
        kept, rejected = deduplicate_records(records)
        assert len(kept) == 2
        assert len(rejected) == 2
        assert rejected[0].rejected_company == "Beta"
        assert rejected[1].rejected_company == "Gamma"

    def test_records_without_dedup_key_included(self):
        records = [
            make_record("Alpha", None),
            make_record("Beta", "b.com"),
        ]
        kept, rejected = deduplicate_records(records)
        assert len(kept) == 2
        assert len(rejected) == 0
        assert {r.company_name for r in kept} == {"Alpha", "Beta"}

    def test_three_way_collision_keeps_best(self):
        records = [
            make_record("A", "key"),
            make_record("B", "key", employee_count=10),
            make_record("C", "key", employee_count=20, revenue_band="$5M"),
        ]
        kept, rejected = deduplicate_records(records)
        assert len(kept) == 1
        assert kept[0].company_name == "C"
        assert len(rejected) == 2
        assert {r.rejected_company for r in rejected} == {"A", "B"}

    def test_empty_records(self):
        kept, rejected = deduplicate_records([])
        assert kept == []
        assert rejected == []

    def test_all_tied_at_zero_enrichment(self):
        records = [
            make_record("Charlie", "key"),
            make_record("Alpha", "key"),
            make_record("Beta", "key"),
        ]
        kept, rejected = deduplicate_records(records)
        assert len(kept) == 1
        assert kept[0].company_name == "Alpha"
        assert len(rejected) == 2
        for r in rejected:
            assert "Tied at 0" in r.reason

    def test_reason_says_fewer_when_unequal(self):
        records = [
            make_record("Rich", "key", employee_count=50, revenue_band="$10M"),
            make_record("Poor", "key"),
        ]
        kept, rejected = deduplicate_records(records)
        assert rejected[0].reason == "Fewer enrichment fields (0 vs 2)"

    def test_empty_string_dedup_key_treated_as_no_key(self):
        records = [
            make_record("Alpha", ""),
            make_record("Beta", "b.com"),
        ]
        kept, rejected = deduplicate_records(records)
        assert len(kept) == 2
        assert len(rejected) == 0

    def test_all_without_dedup_key_passed_through(self):
        records = [
            make_record("A", None),
            make_record("B", None),
            make_record("C", None),
        ]
        kept, rejected = deduplicate_records(records)
        assert len(kept) == 3
        assert len(rejected) == 0

    def test_deterministic_order_for_same_company(self):
        records = [
            make_record("Acme", "key"),
            make_record("Acme", "key", employee_count=10),
        ]
        kept, rejected = deduplicate_records(records)
        assert len(kept) == 1
        assert kept[0].employee_count == 10


class TestRecordToRow:
    def test_all_fields(self):
        r = LeadRecord(
            company_name="Acme",
            website="https://acme.com",
            email="a@a.com",
            phone="555",
            address="Addr",
            industry_code="Tech",
            employee_count=50,
            revenue_band="$10M",
            source_url="https://example.com/listing",
            scraped_at=TIP,
            dedup_key="acme.com",
            lead_score=80,
        )
        row = record_to_row(r)
        assert row == [
            "Acme",
            "https://acme.com",
            "a@a.com",
            "555",
            "Addr",
            "Tech",
            "50",
            "$10M",
            "https://example.com/listing",
            TIP.isoformat(),
            "acme.com",
            "80",
            "",
            "",
        ]

    def test_minimal_fields(self):
        r = LeadRecord(company_name="Minimal")
        row = record_to_row(r)
        assert row == [
            "Minimal", "", "", "", "", "", "", "", "", "", "", "", "", "",
        ]

    def test_zero_employee_count_renders_as_string_zero(self):
        r = LeadRecord(company_name="Test", employee_count=0)
        row = record_to_row(r)
        assert row[6] == "0"

    def test_zero_lead_score_renders_as_string_zero(self):
        r = LeadRecord(company_name="Test", lead_score=0)
        row = record_to_row(r)
        assert row[11] == "0"

    def test_none_dedup_key_renders_as_empty(self):
        r = LeadRecord(company_name="Test", dedup_key=None)
        row = record_to_row(r)
        assert row[10] == ""


class TestRejectedToRow:
    def test_all_fields(self):
        r = RejectedDuplicate(
            dedup_key="key",
            kept_company="Keeper",
            rejected_company="Loser",
            reason="Not enough data",
            timestamp=TIP,
        )
        row = rejected_to_row(r)
        assert row == ["key", "Keeper", "Loser", "Not enough data", TIP.isoformat()]

    def test_no_timestamp(self):
        r = RejectedDuplicate(
            dedup_key="key",
            kept_company="K",
            rejected_company="L",
            reason="test",
        )
        row = rejected_to_row(r)
        assert row == ["key", "K", "L", "test", ""]


class TestWriteRejectedDuplicates:
    def test_writes_to_sheet(self):
        mock_client = MagicMock()
        rejected = [
            RejectedDuplicate(dedup_key="k", kept_company="K", rejected_company="L", reason="test"),
        ]
        write_rejected_duplicates(mock_client, rejected)
        mock_client.append_rows.assert_called_once()
        args = mock_client.append_rows.call_args
        assert args[0][0] == "rejected_duplicates"
        assert len(args[0][1]) == 1

    def test_empty_list_does_nothing(self):
        mock_client = MagicMock()
        write_rejected_duplicates(mock_client, [])
        mock_client.append_rows.assert_not_called()


class TestFilterNewRows:
    def test_skips_existing_keys(self):
        existing = {"existing.com"}
        rows = [
            ["Alpha", "", "", "", "", "", "", "", "", "", "existing.com", ""],
            ["Beta", "", "", "", "", "", "", "", "", "", "new.com", ""],
        ]
        result = filter_new_rows(rows, existing)
        assert len(result) == 1
        assert result[0][10] == "new.com"
        # input set must not be mutated
        assert existing == {"existing.com"}

    def test_all_new_when_no_existing(self):
        rows = [
            ["A", "", "", "", "", "", "", "", "", "", "a.com", ""],
            ["B", "", "", "", "", "", "", "", "", "", "b.com", ""],
        ]
        result = filter_new_rows(rows, set())
        assert len(result) == 2

    def test_keeps_rows_without_key(self):
        existing = {"existing.com"}
        rows = [
            ["Alpha", "", "", "", "", "", "", "", "", "", "", ""],
            ["Beta", "", "", "", "", "", "", "", "", "", "existing.com", ""],
        ]
        result = filter_new_rows(rows, existing)
        assert len(result) == 1
        assert result[0][0] == "Alpha"
        assert existing == {"existing.com"}

    def test_empty_rows(self):
        result = filter_new_rows([], {"existing.com"})
        assert result == []

    def test_custom_key_index(self):
        existing = {"dup"}
        rows = [
            ["key1", "value1"],
            ["dup", "value2"],
            ["key3", "value3"],
        ]
        result = filter_new_rows(rows, existing, dedup_key_index=0)
        assert len(result) == 2
        assert result[0] == ["key1", "value1"]
        assert result[1] == ["key3", "value3"]

    def test_short_row_no_key(self):
        rows = [
            ["Alpha"],
        ]
        result = filter_new_rows(rows, set())
        assert len(result) == 1
        assert result[0] == ["Alpha"]

    def test_does_not_mutate_input_rows(self):
        existing = {"a.com"}
        rows = [
            ["A", "", "", "", "", "", "", "", "", "", "a.com", ""],
        ]
        original = [list(row) for row in rows]
        filter_new_rows(rows, existing)
        assert rows == original

    def test_does_not_mutate_existing_keys(self):
        existing = {"a.com"}
        filter_new_rows([["A", "", "", "", "", "", "", "", "", "", "b.com", ""]], existing)
        assert existing == {"a.com"}

    def test_all_rows_skipped_when_all_keys_exist(self):
        existing = {"a.com", "b.com"}
        rows = [
            ["A", "", "", "", "", "", "", "", "", "", "a.com", ""],
            ["B", "", "", "", "", "", "", "", "", "", "b.com", ""],
        ]
        result = filter_new_rows(rows, existing)
        assert result == []

    def test_duplicate_key_within_same_batch_deduplicated(self):
        existing = {"existing.com"}
        rows = [
            ["A", "", "", "", "", "", "", "", "", "", "dup.com", ""],
            ["B", "", "", "", "", "", "", "", "", "", "dup.com", ""],
        ]
        result = filter_new_rows(rows, existing)
        assert len(result) == 1  # second dup is skipped by internal seen set
        assert result[0][0] == "A"

    def test_row_shorter_than_key_index(self):
        existing = {"key"}
        rows = [
            ["short"],
        ]
        result = filter_new_rows(rows, existing)
        assert len(result) == 1
        assert result[0] == ["short"]

    def test_all_rows_without_keys(self):
        existing = {"existing.com"}
        rows = [
            ["A", ""],
            ["B", ""],
        ]
        result = filter_new_rows(rows, existing)
        assert len(result) == 2


class TestIntegrationDedupAndSheetFilter:
    def test_full_dedup_flow_prevents_double_write(self):
        records = [
            make_record("Beta", "same-key"),
            make_record("Alpha", "same-key", employee_count=100),
        ]
        kept, rejected = deduplicate_records(records)
        assert len(kept) == 1
        assert kept[0].company_name == "Alpha"
        assert len(rejected) == 1

        rows = [record_to_row(r) for r in kept]
        sheet_keys_after_first_run = set()
        first_write = filter_new_rows(rows, sheet_keys_after_first_run)
        assert len(first_write) == 1
        written_key = first_write[0][10]
        sheet_keys_after_first_run.add(written_key)

        second_write = filter_new_rows(rows, sheet_keys_after_first_run)
        assert len(second_write) == 0

    def test_multiple_dedup_groups_two_runs(self):
        r1a = make_record("Alpha", "a.com", employee_count=100)
        r1b = make_record("AlphaDup", "a.com")
        r2a = make_record("Beta", "b.com", revenue_band="$50M")
        r2b = make_record("BetaDup", "b.com", employee_count=10)

        kept, rejected = deduplicate_records([r1a, r1b, r2a, r2b])
        assert len(kept) == 2
        assert len(rejected) == 2
        assert {k.company_name for k in kept} == {"Alpha", "Beta"}

        rows = [record_to_row(r) for r in kept]
        sheet_keys = set()
        first_write = filter_new_rows(rows, sheet_keys)
        assert len(first_write) == 2
        sheet_keys.update(r[10] for r in first_write)

        # Second run: same scraped records come back
        kept2, rejected2 = deduplicate_records([r1a, r1b, r2a, r2b])
        assert len(kept2) == 2
        rows2 = [record_to_row(r) for r in kept2]
        second_write = filter_new_rows(rows2, sheet_keys)
        assert len(second_write) == 0

    def test_rejected_duplicates_logged_correctly(self):
        records = [
            make_record("Winner", "key", employee_count=100, revenue_band="$10M"),
            make_record("Loser", "key"),
        ]
        kept, rejected = deduplicate_records(records)
        assert len(rejected) == 1
        rd = rejected[0]
        assert rd.dedup_key == "key"
        assert rd.kept_company == "Winner"
        assert rd.rejected_company == "Loser"
        assert rd.reason == "Fewer enrichment fields (0 vs 2)"
        assert rd.timestamp is not None


class TestSchemaAlignment:
    def test_record_to_row_length_matches_headers(self):
        r = LeadRecord(company_name="Test")
        assert len(record_to_row(r)) == len(LEADS_HEADERS)

    def test_dedup_key_index_matches_headers(self):
        assert LEADS_HEADERS.index("dedup_key") == DEDUP_KEY_INDEX


class TestAppendIfNotDuplicateOrchestration:
    def test_reads_keys_and_filters_and_appends(self):
        from src.database.client import DatabaseClient
        client = DatabaseClient.__new__(DatabaseClient)
        client.conn = MagicMock()
        client.read_existing_dedup_keys = MagicMock(return_value={"existing.com"})
        client.append_rows = MagicMock()

        rows = [
            ["Alpha", "", "", "", "", "", "", "", "", "", "existing.com", ""],
            ["Beta",  "", "", "", "", "", "", "", "", "", "new.com", ""],
        ]
        written = client.append_if_not_duplicate("staging", rows)
        assert len(written) == 1
        assert written[0][0] == "Beta"
        client.append_rows.assert_called_once()
        called_rows = client.append_rows.call_args[0][1]
        assert len(called_rows) == 1
        assert called_rows[0][0] == "Beta"

    def test_additional_tabs_merged(self):
        from src.database.client import DatabaseClient
        client = DatabaseClient.__new__(DatabaseClient)
        client.conn = MagicMock()
        client.read_existing_dedup_keys = MagicMock(
            side_effect=lambda t: {"staging": {"dup1"}, "Leads": {"dup2"}}.get(t, set())
        )
        client.append_rows = MagicMock()

        rows = [
            ["A", "", "", "", "", "", "", "", "", "", "dup1", ""],
            ["B", "", "", "", "", "", "", "", "", "", "dup2", ""],
            ["C", "", "", "", "", "", "", "", "", "", "new", ""],
        ]
        written = client.append_if_not_duplicate("staging", rows, additional_tabs=["Leads"])
        assert len(written) == 1
        assert written[0][0] == "C"

    def test_empty_rows_does_nothing(self):
        from src.database.client import DatabaseClient
        client = DatabaseClient.__new__(DatabaseClient)
        client.conn = MagicMock()
        client.read_existing_dedup_keys = MagicMock(return_value=set())
        client.append_rows = MagicMock()

        written = client.append_if_not_duplicate("staging", [])
        assert written == []
        client.append_rows.assert_not_called()

    def test_additional_tabs_none_is_same_as_empty(self):
        from src.database.client import DatabaseClient
        client = DatabaseClient.__new__(DatabaseClient)
        client.conn = MagicMock()
        client.read_existing_dedup_keys = MagicMock(return_value=set())
        client.append_rows = MagicMock()

        rows = [["A", "", "", "", "", "", "", "", "", "", "new.com", ""]]
        written_none = client.append_if_not_duplicate("staging", rows, additional_tabs=None)
        assert len(written_none) == 1
