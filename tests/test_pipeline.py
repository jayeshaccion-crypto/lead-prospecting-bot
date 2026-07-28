from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from src.models import LeadRecord, ScrapeError, RejectedDuplicate
from src.pipeline import (
    check_failure_threshold,
    promote_to_production,
    run_summary,
    scrape_error_to_row,
    main_pipeline,
    PipelineThresholdError,
    record_to_row,
    rejected_to_row,
    write_rejected_duplicates,
    _enrichment_field_count,
)


TIP = datetime(2025, 6, 1, tzinfo=timezone.utc)


def _stub_db_client(get_all_rows_return=None):
    """Build a mock DatabaseClient with side_effect on get_all_rows."""

    class _MockClient(MagicMock):
        pass

    client = _MockClient()

    def _get_all_rows(tab):
        data = {
            "scrape_errors": [["url", "timestamp", "error_type"]],
            "staging": get_all_rows_return or [],
            "Leads": [["company_name", "website"]],
        }
        return data.get(tab, [])

    client.get_all_rows.side_effect = _get_all_rows
    return client


class TestCheckFailureThreshold:
    def test_below_threshold_returns_true(self):
        errors = [ScrapeError(url="https://a.com", timestamp=TIP, error_type="Timeout")]
        assert check_failure_threshold(errors, total_targets=10) is True

    def test_at_exactly_30_percent_returns_true(self):
        errors = [ScrapeError(url="https://a.com", timestamp=TIP, error_type="Err") for _ in range(3)]
        assert check_failure_threshold(errors, total_targets=10) is True

    def test_above_threshold_returns_false(self):
        errors = [ScrapeError(url="https://a.com", timestamp=TIP, error_type="Err") for _ in range(4)]
        assert check_failure_threshold(errors, total_targets=10) is False

    def test_no_errors_returns_true(self):
        assert check_failure_threshold([], total_targets=5) is True

    def test_no_targets_returns_true(self):
        errors = [ScrapeError(url="https://a.com", timestamp=TIP, error_type="Err")]
        assert check_failure_threshold(errors, total_targets=0) is True

    @patch("src.pipeline.load_targets_config", return_value=[{"entry_url": "https://a.com"}])
    def test_loads_config_when_total_not_given(self, mock_config):
        errors = []
        assert check_failure_threshold(errors) is True


class TestScrapeErrorToRow:
    def test_all_fields(self):
        e = ScrapeError(url="https://err.com", timestamp=TIP, error_type="Timeout")
        assert scrape_error_to_row(e) == ["https://err.com", TIP.isoformat(), "Timeout"]

    def test_no_timestamp(self):
        e = ScrapeError(url="https://err.com", error_type=None)
        row = scrape_error_to_row(e)
        assert row == ["https://err.com", "", ""]


class TestEnrichmentFieldCount:
    def test_returns_0_when_neither_populated(self):
        r = LeadRecord(company_name="Acme", email="a@a.com", dedup_key="k", scraped_at=TIP)
        assert _enrichment_field_count(r) == 0

    def test_returns_1_when_only_employee_count(self):
        r = LeadRecord(company_name="Acme", email="a@a.com", dedup_key="k", scraped_at=TIP, employee_count=50)
        assert _enrichment_field_count(r) == 1

    def test_returns_1_when_only_revenue_band(self):
        r = LeadRecord(company_name="Acme", email="a@a.com", dedup_key="k", scraped_at=TIP, revenue_band="1M-5M")
        assert _enrichment_field_count(r) == 1

    def test_returns_2_when_both_populated(self):
        r = LeadRecord(
            company_name="Acme", email="a@a.com", dedup_key="k", scraped_at=TIP,
            employee_count=50, revenue_band="1M-5M",
        )
        assert _enrichment_field_count(r) == 2


class TestRecordToRow:
    def test_all_fields(self):
        r = LeadRecord(
            company_name="Acme", website="https://acme.com", email="a@a.com",
            phone="555-0100", address="123 Main", industry_code="IT",
            employee_count=50, revenue_band="1M-5M", source_url="https://src.com",
            scraped_at=TIP, dedup_key="acme.com", lead_score=80,
        )
        row = record_to_row(r)
        assert row[0] == "Acme"
        assert row[1] == "https://acme.com"
        assert row[2] == "a@a.com"
        assert row[3] == "555-0100"
        assert row[4] == "123 Main"
        assert row[5] == "IT"
        assert row[6] == "50"
        assert row[7] == "1M-5M"
        assert row[8] == "https://src.com"
        assert row[9] == TIP.isoformat()
        assert row[10] == "acme.com"
        assert row[11] == "80"

    def test_none_fields_become_empty_strings(self):
        r = LeadRecord(company_name="Acme", scraped_at=TIP)
        row = record_to_row(r)
        for i in range(1, len(row)):
            if i != 9:
                assert row[i] == "", f"Index {i} should be empty but got {row[i]!r}"

    def test_employee_count_none_is_empty_string(self):
        r = LeadRecord(company_name="Acme", scraped_at=TIP)
        row = record_to_row(r)
        assert row[6] == ""

    def test_lead_score_none_is_empty_string(self):
        r = LeadRecord(company_name="Acme", scraped_at=TIP)
        row = record_to_row(r)
        assert row[11] == ""

    def test_scraped_at_none_is_empty_string(self):
        r = LeadRecord(company_name="Acme")
        row = record_to_row(r)
        assert row[9] == ""


class TestRejectedToRow:
    def test_all_fields(self):
        reject = RejectedDuplicate(
            dedup_key="acme.com", kept_company="Acme", rejected_company="Beta",
            reason="Fewer enrichment fields", timestamp=TIP,
        )
        row = rejected_to_row(reject)
        assert row == ["acme.com", "Acme", "Beta", "Fewer enrichment fields", TIP.isoformat()]

    def test_none_timestamp_becomes_empty(self):
        reject = RejectedDuplicate(
            dedup_key="k", kept_company="A", rejected_company="B", reason="test",
        )
        row = rejected_to_row(reject)
        assert row[4] == ""


class TestWriteRejectedDuplicates:
    def test_skips_when_empty_list(self):
        client = MagicMock()
        write_rejected_duplicates(client, [])
        client.append_rows.assert_not_called()

    def test_writes_converted_rows(self):
        client = MagicMock()
        reject = RejectedDuplicate(
            dedup_key="k", kept_company="A", rejected_company="B", reason="test", timestamp=TIP,
        )
        write_rejected_duplicates(client, [reject])
        client.append_rows.assert_called_once()
        args = client.append_rows.call_args[0]
        assert args[0] == "rejected_duplicates"
        assert args[1] == [["k", "A", "B", "test", TIP.isoformat()]]

    def test_writes_to_custom_tab(self):
        client = MagicMock()
        reject = RejectedDuplicate(
            dedup_key="k", kept_company="A", rejected_company="B", reason="test", timestamp=TIP,
        )
        write_rejected_duplicates(client, [reject], tab="custom_tab")
        client.append_rows.assert_called_once_with("custom_tab", [["k", "A", "B", "test", TIP.isoformat()]])

    def test_logs_row_count(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        client = MagicMock()
        rejects = [
            RejectedDuplicate(dedup_key="k1", kept_company="A", rejected_company="B", reason="r1", timestamp=TIP),
            RejectedDuplicate(dedup_key="k2", kept_company="C", rejected_company="D", reason="r2", timestamp=TIP),
        ]
        write_rejected_duplicates(client, rejects)
        assert any("Wrote 2 rejected duplicate rows" in r.message for r in caplog.records if r.levelname == "INFO")


class TestPromoteToProduction:
    def test_copies_staging_rows_to_leads(self):
        mock_client = _stub_db_client(
            [["company_name", "website"], ["Acme", "acme.com"], ["Beta", "beta.com"]],
        )
        mock_client.append_if_not_duplicate.return_value = [
            ["Acme", "acme.com"], ["Beta", "beta.com"],
        ]
        promote_to_production(client=mock_client)
        mock_client.append_if_not_duplicate.assert_called_once_with(
            "Leads", [["Acme", "acme.com"], ["Beta", "beta.com"]],
        )

    def test_skips_when_only_headers(self):
        mock_client = _stub_db_client([["company_name", "website"]])
        promote_to_production(client=mock_client)
        mock_client.append_if_not_duplicate.assert_not_called()
        mock_client.append_rows.assert_not_called()

    def test_skips_when_no_data_rows(self):
        mock_client = _stub_db_client(
            [["company_name", "website"], ["", ""], [" ", "  "]],
        )
        promote_to_production(client=mock_client)
        mock_client.append_if_not_duplicate.assert_not_called()
        mock_client.append_rows.assert_not_called()

    @patch("src.pipeline.load_targets_config", return_value=[])
    @patch("src.database.client.DatabaseClient")
    def test_creates_own_client_when_none(self, mock_client_cls, mock_config):
        mock_client = mock_client_cls.return_value
        mock_client.get_all_rows.side_effect = lambda tab: {
            "scrape_errors": [["url", "timestamp", "error_type"]],
            "staging": [["h"], ["Acme", "acme.com"]],
        }.get(tab, [])
        mock_client.append_if_not_duplicate.return_value = [["Acme", "acme.com"]]
        promote_to_production()
        mock_client.append_if_not_duplicate.assert_called_once()


class TestRunSummary:
    def test_returns_correct_dict(self):
        s = run_summary(
            raw_count=100,
            enriched_count=80,
            kept_count=75,
            rejected_dup_count=5,
            error_count=2,
            invalid_count=0,
        )
        assert s == {
            "scraped": 100,
            "enriched_count": 80,
            "kept_after_validation": 75,
            "rejected_duplicates": 5,
            "errors": 2,
            "invalid_records": 0,
        }


@contextmanager
def _pipeline_context(
    dry_run,
    scrape_result=([], []),
    threshold_ok=True,
):
    """Context manager that patches all deps of main_pipeline and yields mock dict."""
    stacks = [
        patch("src.database.client.DatabaseClient"),
        patch("src.database.tabs.ensure_all_tabs"),
        patch("src.database.tabs.write_staging"),
        patch("src.scraper.engine.scrape_all_targets", return_value=scrape_result),
        patch("src.pipeline.check_failure_threshold", return_value=threshold_ok),
        patch("src.pipeline.promote_to_production"),
        patch("src.pipeline.filter_valid_records", side_effect=lambda r, **kw: (r, [])),
    ]
    mocks = {}
    for s in stacks:
        mocks[s.attribute] = s.start()
    try:
        yield mocks
    finally:
        for s in reversed(stacks):
            s.stop()


class TestMainPipeline:
    def test_dry_run_does_not_promote(self):
        with _pipeline_context(dry_run=True) as m:
            main_pipeline(dry_run=True)
            m["promote_to_production"].assert_not_called()

    def test_dry_run_calls_write_staging(self):
        with _pipeline_context(dry_run=True, scrape_result=([], [])) as m:
            main_pipeline(dry_run=True)
            assert m["write_staging"].called

    def test_full_pipeline_calls_promote(self):
        with _pipeline_context(dry_run=False, scrape_result=([], []), threshold_ok=True) as m:
            main_pipeline(dry_run=False)
            assert m["promote_to_production"].called

    def test_threshold_failure_raises_error(self):
        with pytest.raises(PipelineThresholdError):
            with _pipeline_context(dry_run=False, scrape_result=([], []), threshold_ok=False):
                main_pipeline(dry_run=False)

    def test_pipeline_counts(self):
        record = LeadRecord(
            company_name="Acme", website="https://acme.com", email="a@a.com",
            dedup_key="acme.com", scraped_at=TIP,
        )
        scrape_result = (
            [record],
            [ScrapeError(url="https://bad.com", timestamp=TIP, error_type="Err")],
        )
        with _pipeline_context(dry_run=False, scrape_result=scrape_result, threshold_ok=True) as m:
            summary = main_pipeline(dry_run=False)
            assert summary["scraped"] == 1
            assert summary["errors"] == 1
            assert summary["enriched_count"] == 0
            assert m["promote_to_production"].called

    def test_write_staging_gets_converted_rows(self):
        record = LeadRecord(
            company_name="Acme", email="a@a.com", dedup_key="acme.com",
            scraped_at=TIP, lead_score=40,
        )
        with _pipeline_context(dry_run=True, scrape_result=([record], [])) as m:
            main_pipeline(dry_run=True)
            lead_rows = m["write_staging"].call_args[0][1]
            assert isinstance(lead_rows, list)
            assert len(lead_rows) == 1
            assert lead_rows[0][0] == "Acme"

    def test_dry_run_summary_structure(self):
        with _pipeline_context(dry_run=True, scrape_result=([], [])):
            summary = main_pipeline(dry_run=True)
            assert "scraped" in summary and "elapsed" in summary
            assert set(summary.keys()) >= {"scraped", "enriched_count", "kept_after_validation",
                                            "rejected_duplicates", "errors", "invalid_records"}

    def test_writes_error_rows_to_scrape_errors_tab(self):
        record = LeadRecord(
            company_name="Acme", email="a@a.com", dedup_key="acme.com",
            scraped_at=TIP,
        )
        scrape_result = (
            [record],
            [ScrapeError(url="https://bad.com", timestamp=TIP, error_type="Timeout")],
        )
        with _pipeline_context(dry_run=True, scrape_result=scrape_result) as m:
            main_pipeline(dry_run=True)
            client_instance = m["DatabaseClient"].return_value
            calls = client_instance.append_rows.call_args_list
            error_calls = [c for c in calls if c[0][0] == "scrape_errors"]
            assert len(error_calls) == 1
            assert len(error_calls[0][0][1]) == 1

    def test_writes_rejected_duplicates_tab(self):
        r1 = LeadRecord(
            company_name="Alpha", dedup_key="key", scraped_at=TIP,
            employee_count=100,
        )
        r2 = LeadRecord(
            company_name="Beta", dedup_key="key", scraped_at=TIP,
        )
        scrape_result = ([r1, r2], [])
        with _pipeline_context(dry_run=True, scrape_result=scrape_result) as m:
            main_pipeline(dry_run=True)
            client_instance = m["DatabaseClient"].return_value
            calls = client_instance.append_rows.call_args_list
            rejected_calls = [c for c in calls if c[0][0] == "rejected_duplicates"]
            assert len(rejected_calls) == 1
            assert len(rejected_calls[0][0][1]) == 1


class TestPipelineThresholdError:
    def test_is_exception_subclass(self):
        assert issubclass(PipelineThresholdError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(PipelineThresholdError):
            raise PipelineThresholdError("test")


class TestEnsureAllTabs:
    def test_creates_missing_tabs(self):
        client = MagicMock()
        client.ensure_tab.side_effect = lambda name, headers: True
        from src.database.tabs import ensure_all_tabs
        result = ensure_all_tabs(client)
        assert client.ensure_tab.call_count == 4
        assert result["Leads"] is True
        assert result["staging"] is True

    def test_skips_existing_tabs(self):
        client = MagicMock()
        client.ensure_tab.side_effect = lambda name, headers: False
        from src.database.tabs import ensure_all_tabs
        result = ensure_all_tabs(client)
        assert all(v is False for v in result.values())

    def test_logs_newly_created_tabs(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        client = MagicMock()
        created = {"Leads": False, "staging": True, "scrape_errors": True, "rejected_duplicates": False}
        client.ensure_tab.side_effect = lambda name, headers: created.get(name, False)
        from src.database.tabs import ensure_all_tabs
        ensure_all_tabs(client)
        assert any("Created database tables: staging, scrape_errors" in r.message for r in caplog.records if r.levelname == "INFO")

    def test_no_log_when_none_created(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        client = MagicMock()
        client.ensure_tab.return_value = False
        from src.database.tabs import ensure_all_tabs
        ensure_all_tabs(client)
        created_logs = [r for r in caplog.records if "Created database tables" in r.message]
        assert len(created_logs) == 0


class TestWriteStaging:
    def test_clears_and_writes_headers_and_rows(self):
        client = MagicMock()
        from src.database.tabs import write_staging

        rows = [["Acme", "acme.com"]]
        write_staging(client, rows)
        client.clear_tab.assert_called_once_with("staging")
        client.append_rows.assert_called_once()
        args = client.append_rows.call_args[0]
        assert args[0] == "staging"
        expected_header = ["company_name", "website", "email", "phone", "address",
                           "industry_code", "employee_count", "revenue_band",
                           "source_url", "scraped_at", "dedup_key", "lead_score"]
        assert args[1][0] == expected_header
        assert args[1][1] == ["Acme", "acme.com"]

    def test_empty_rows_writes_headers_only(self):
        client = MagicMock()
        from src.database.tabs import write_staging

        write_staging(client, [])
        client.append_rows.assert_called_once()
        args = client.append_rows.call_args[0]
        assert len(args[1]) == 1

    def test_clears_tab_before_each_write(self):
        client = MagicMock()
        from src.database.tabs import write_staging

        write_staging(client, [["A", "a.com"]])
        write_staging(client, [["B", "b.com"]])
        assert client.clear_tab.call_count == 2
        assert client.append_rows.call_count == 2

    def test_logs_row_count(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        client = MagicMock()
        from src.database.tabs import write_staging

        write_staging(client, [["Acme", "acme.com"], ["Beta", "beta.com"]])
        assert any("Wrote 3 rows" in r.message for r in caplog.records if r.levelname == "INFO")


class TestRunSummaryEdgeCases:
    def test_zero_values(self):
        s = run_summary(
            raw_count=0, enriched_count=0, kept_count=0,
            rejected_dup_count=0, error_count=0, invalid_count=0,
        )
        assert s == {
            "scraped": 0, "enriched_count": 0,             "kept_after_validation": 0,
            "rejected_duplicates": 0, "errors": 0, "invalid_records": 0,
        }

    def test_single_digit_values(self):
        s = run_summary(
            raw_count=1, enriched_count=1, kept_count=1,
            rejected_dup_count=0, error_count=0, invalid_count=0,
        )
        assert s["scraped"] == 1
        assert s["kept_after_validation"] == 1


class TestCheckFailureThresholdEdgeCases:
    def test_with_integer_error_count(self):
        assert check_failure_threshold(3, total_targets=10) is True
        assert check_failure_threshold(4, total_targets=10) is False

    def test_zero_percent_failure(self):
        assert check_failure_threshold(0, total_targets=5) is True

    def test_hundred_percent_failure(self):
        assert check_failure_threshold(5, total_targets=5) is False

    def test_33_percent_above_threshold(self):
        assert check_failure_threshold(1, total_targets=3) is False

    def test_25_percent_below_threshold(self):
        assert check_failure_threshold(1, total_targets=4) is True

    def test_empty_list_no_targets_returns_true(self):
        assert check_failure_threshold([], total_targets=0) is True

    @patch("src.pipeline.load_targets_config", return_value=[])
    def test_loads_config_empty_returns_true(self, mock_config):
        assert check_failure_threshold([], total_targets=None) is True


class TestPromoteToProductionEdgeCases:
    def test_threshold_check_fail_aborts(self):
        client = _stub_db_client()
        client.get_all_rows.side_effect = lambda tab: {
            "scrape_errors": [
                ["url", "timestamp", "error_type"],
                ["https://err1.com", "ts", "Timeout"],
                ["https://err2.com", "ts", "Err"],
            ],
            "staging": [["company_name", "website"], ["Acme", "acme.com"]],
        }.get(tab, [])
        with patch("src.pipeline.load_targets_config", return_value=[{"url": "https://a.com"}]):
            promote_to_production(client=client)
        client.append_if_not_duplicate.assert_not_called()

    def test_threshold_check_pass_proceeds(self):
        client = _stub_db_client()
        client.get_all_rows.side_effect = lambda tab: {
            "scrape_errors": [["url", "timestamp", "error_type"]],
            "staging": [["company_name", "website"], ["Acme", "acme.com"]],
        }.get(tab, [])
        client.append_if_not_duplicate.return_value = [["Acme", "acme.com"]]
        with patch("src.pipeline.load_targets_config", return_value=[{"url": "https://a.com"}]):
            promote_to_production(client=client)
        client.append_if_not_duplicate.assert_called_once()

    def test_duplicate_error_urls_counted_once(self):
        client = _stub_db_client()
        client.get_all_rows.side_effect = lambda tab: {
            "scrape_errors": [
                ["url", "timestamp", "error_type"],
                ["https://err1.com", "ts", "Timeout"],
                ["https://err1.com", "ts", "Timeout"],
                ["https://err1.com", "ts", "Timeout"],
            ],
            "staging": [["company_name", "website"], ["Acme", "acme.com"]],
        }.get(tab, [])
        client.append_if_not_duplicate.return_value = [["Acme", "acme.com"]]
        with patch("src.pipeline.load_targets_config", return_value=[{"url": "https://a.com"}]):
            promote_to_production(client=client)
        client.append_if_not_duplicate.assert_not_called()

    def test_missing_scrape_errors_tab_does_not_crash(self):
        client = _stub_db_client()
        client.get_all_rows.side_effect = lambda tab: {
            "staging": [["company_name", "website"], ["Acme", "acme.com"]],
        }.get(tab, [])
        client.append_if_not_duplicate.return_value = [["Acme", "acme.com"]]
        with patch("src.pipeline.load_targets_config", return_value=[]):
            promote_to_production(client=client)
        client.append_if_not_duplicate.assert_called_once()

    def test_missing_staging_tab_does_not_crash(self):
        client = _stub_db_client()
        client.get_all_rows.side_effect = Exception("Tab not found")
        with patch("src.pipeline.load_targets_config", return_value=[]):
            promote_to_production(client=client)
        client.append_if_not_duplicate.assert_not_called()

    def test_skip_threshold_check_skips_check(self):
        client = _stub_db_client()
        client.get_all_rows.side_effect = lambda tab: {
            "staging": [["h"], ["Acme", "acme.com"]],
        }.get(tab, [])
        client.append_if_not_duplicate.return_value = [["Acme", "acme.com"]]
        promote_to_production(client=client, skip_threshold_check=True)
        client.append_if_not_duplicate.assert_called_once()

    def test_all_empty_data_rows_skipped(self):
        client = _stub_db_client()
        client.get_all_rows.side_effect = lambda tab: {
            "scrape_errors": [["url", "timestamp", "error_type"]],
            "staging": [["company_name", "website"], ["", ""], [" ", "  "]],
        }.get(tab, [])
        with patch("src.pipeline.load_targets_config", return_value=[]):
            promote_to_production(client=client)
        client.append_if_not_duplicate.assert_not_called()


class TestMainPipelineEdgeCases:
    def test_promote_called_with_skip_threshold_check(self):
        record = LeadRecord(
            company_name="Acme", email="a@a.com", dedup_key="acme.com", scraped_at=TIP,
        )
        with _pipeline_context(dry_run=False, scrape_result=([record], []), threshold_ok=True) as m:
            main_pipeline(dry_run=False)
            m["promote_to_production"].assert_called_once()
            _, kwargs = m["promote_to_production"].call_args
            assert kwargs.get("skip_threshold_check") is True

    def test_invalid_records_excluded_from_staging(self):
        record = LeadRecord(
            company_name="Valid", email="v@v.com", dedup_key="v.com", scraped_at=TIP,
        )
        with _pipeline_context(dry_run=True, scrape_result=([record], [])) as m:
            m["filter_valid_records"].side_effect = lambda r, **kw: ([], [(r[0], "Rejected")])
            main_pipeline(dry_run=True)
            lead_rows = m["write_staging"].call_args[0][1]
            assert lead_rows == []

    def test_no_error_rows_skips_scrape_errors_write(self):
        record = LeadRecord(
            company_name="Acme", email="a@a.com", dedup_key="acme.com", scraped_at=TIP,
        )
        with _pipeline_context(dry_run=True, scrape_result=([record], [])) as m:
            main_pipeline(dry_run=True)
            client_instance = m["DatabaseClient"].return_value
            calls = client_instance.append_rows.call_args_list
            error_calls = [c for c in calls if c[0][0] == "scrape_errors"]
            assert len(error_calls) == 0

    def test_no_rejected_rows_skips_rejected_write(self):
        record = LeadRecord(
            company_name="Acme", email="a@a.com", dedup_key="acme.com", scraped_at=TIP,
        )
        with _pipeline_context(dry_run=True, scrape_result=([record], [])) as m:
            main_pipeline(dry_run=True)
            client_instance = m["DatabaseClient"].return_value
            calls = client_instance.append_rows.call_args_list
            rejected_calls = [c for c in calls if c[0][0] == "rejected_duplicates"]
            assert len(rejected_calls) == 0

    def test_threshold_failure_still_writes_staging(self):
        record = LeadRecord(
            company_name="Acme", email="a@a.com", dedup_key="acme.com", scraped_at=TIP,
        )
        scrape_result = ([record], [])
        with pytest.raises(PipelineThresholdError):
            with _pipeline_context(dry_run=False, scrape_result=scrape_result, threshold_ok=False) as m:
                main_pipeline(dry_run=False)
                assert m["write_staging"].called
                client_instance = m["DatabaseClient"].return_value
                calls = client_instance.append_rows.call_args_list
                error_calls = [c for c in calls if c[0][0] == "scrape_errors"]
                rejected_calls = [c for c in calls if c[0][0] == "rejected_duplicates"]
                # staging, errors, rejected should all be written before threshold is checked
                assert m["write_staging"].called
                assert len(error_calls) == 0
                assert len(rejected_calls) == 0

    def test_empty_scrape_result(self):
        with _pipeline_context(dry_run=True, scrape_result=([], [])) as m:
            summary = main_pipeline(dry_run=True)
            assert summary["scraped"] == 0
            assert summary["errors"] == 0
            assert summary["kept_after_validation"] == 0
            assert m["write_staging"].called
            lead_rows = m["write_staging"].call_args[0][1]
            assert lead_rows == []

    def test_includes_elapsed_in_summary(self):
        with _pipeline_context(dry_run=True, scrape_result=([], [])):
            summary = main_pipeline(dry_run=True)
            assert "elapsed" in summary
            assert isinstance(summary["elapsed"], float)
            assert summary["elapsed"] >= 0

    def test_logs_pipeline_timing(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        with _pipeline_context(dry_run=True, scrape_result=([], [])):
            main_pipeline(dry_run=True)
        info_messages = [r.message for r in caplog.records if r.levelname == "INFO"]
        assert any("Setup complete" in msg for msg in info_messages)
        assert any("Pipeline complete" in msg for msg in info_messages)

    def test_logs_scrape_timing(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        record = LeadRecord(
            company_name="Acme", email="a@a.com", dedup_key="acme.com", scraped_at=TIP,
        )
        with _pipeline_context(dry_run=True, scrape_result=([record], [])):
            main_pipeline(dry_run=True)
        info_messages = [r.message for r in caplog.records if r.levelname == "INFO"]
        assert any("Scraped 1 raw records" in msg for msg in info_messages)
        assert any("0 target errors" in msg for msg in info_messages)

    def test_logs_dedup_timing(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        record = LeadRecord(
            company_name="Acme", email="a@a.com", dedup_key="acme.com", scraped_at=TIP,
        )
        with _pipeline_context(dry_run=True, scrape_result=([record], [])):
            main_pipeline(dry_run=True)
        info_messages = [r.message for r in caplog.records if r.levelname == "INFO"]
        assert any("After dedup: 1 kept, 0 rejected duplicates" in msg for msg in info_messages)

    def test_logs_formatted_summary_with_elapsed(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        with _pipeline_context(dry_run=True, scrape_result=([], [])):
            main_pipeline(dry_run=True)
        info_messages = [r.message for r in caplog.records if r.levelname == "INFO"]
        assert any("scraped=0" in msg and "elapsed=" in msg for msg in info_messages)


class TestMainPipelineWithRealValidation:
    """Exercises the real filter_valid_records through main_pipeline."""

    def test_invalid_records_excluded_from_staging(self):
        valid_record = LeadRecord(
            company_name="ValidCo", email="v@v.com", phone="555",
            dedup_key="valid.com", scraped_at=TIP,
        )
        invalid_record = LeadRecord.model_construct(
            company_name="", email="x@x.com", phone="555",
            dedup_key="invalid.com", scraped_at=TIP,
        )
        scrape_result = ([valid_record, invalid_record], [])
        stacks = [
            patch("src.database.client.DatabaseClient"),
            patch("src.database.tabs.ensure_all_tabs"),
            patch("src.database.tabs.write_staging"),
            patch("src.scraper.engine.scrape_all_targets", return_value=scrape_result),
            patch("src.pipeline.check_failure_threshold", return_value=True),
            patch("src.pipeline.promote_to_production"),
        ]
        mocks = {}
        for s in stacks:
            mocks[s.attribute] = s.start()
        try:
            main_pipeline(dry_run=True)
            lead_rows = mocks["write_staging"].call_args[0][1]
            assert len(lead_rows) == 1
            assert lead_rows[0][0] == "ValidCo"
        finally:
            for s in reversed(stacks):
                s.stop()

    def test_invalid_email_gets_prefixed_in_staging(self):
        record = LeadRecord(
            company_name="BadEmailCo", email="bad-email", phone="555",
            dedup_key="bad-email.com", scraped_at=TIP,
        )
        scrape_result = ([record], [])
        stacks = [
            patch("src.database.client.DatabaseClient"),
            patch("src.database.tabs.ensure_all_tabs"),
            patch("src.database.tabs.write_staging"),
            patch("src.scraper.engine.scrape_all_targets", return_value=scrape_result),
            patch("src.pipeline.check_failure_threshold", return_value=True),
            patch("src.pipeline.promote_to_production"),
        ]
        mocks = {}
        for s in stacks:
            mocks[s.attribute] = s.start()
        try:
            main_pipeline(dry_run=True)
            lead_rows = mocks["write_staging"].call_args[0][1]
            assert len(lead_rows) == 1
            assert lead_rows[0][2] == "UNVERIFIED:bad-email"
        finally:
            for s in reversed(stacks):
                s.stop()

    def test_mixed_valid_invalid_summary_count(self):
        valid_record = LeadRecord(
            company_name="ValidCo", email="v@v.com", phone="555",
            dedup_key="valid.com", scraped_at=TIP,
        )
        invalid_record = LeadRecord.model_construct(
            company_name="", email="x@x.com", phone="555",
            dedup_key="invalid.com", scraped_at=TIP,
        )
        scrape_result = ([valid_record, invalid_record], [])
        stacks = [
            patch("src.database.client.DatabaseClient"),
            patch("src.database.tabs.ensure_all_tabs"),
            patch("src.database.tabs.write_staging"),
            patch("src.scraper.engine.scrape_all_targets", return_value=scrape_result),
            patch("src.pipeline.check_failure_threshold", return_value=True),
            patch("src.pipeline.promote_to_production"),
        ]
        mocks = {}
        for s in stacks:
            mocks[s.attribute] = s.start()
        try:
            summary = main_pipeline(dry_run=True)
            assert summary["invalid_records"] == 1
            assert summary["kept_after_validation"] == 1
            assert summary["scraped"] == 2
        finally:
            for s in reversed(stacks):
                s.stop()

    def test_all_invalid_records_empty_staging(self):
        invalid_record = LeadRecord.model_construct(
            company_name="", email="x@x.com", phone="555",
            dedup_key="invalid.com", scraped_at=TIP,
        )
        scrape_result = ([invalid_record], [])
        stacks = [
            patch("src.database.client.DatabaseClient"),
            patch("src.database.tabs.ensure_all_tabs"),
            patch("src.database.tabs.write_staging"),
            patch("src.scraper.engine.scrape_all_targets", return_value=scrape_result),
            patch("src.pipeline.check_failure_threshold", return_value=True),
            patch("src.pipeline.promote_to_production"),
        ]
        mocks = {}
        for s in stacks:
            mocks[s.attribute] = s.start()
        try:
            summary = main_pipeline(dry_run=True)
            assert summary["invalid_records"] == 1
            assert summary["kept_after_validation"] == 0
            lead_rows = mocks["write_staging"].call_args[0][1]
            assert lead_rows == []
        finally:
            for s in reversed(stacks):
                s.stop()


class TestMainCli:
    def test_dry_run_calls_main_pipeline(self):
        with patch("sys.argv", ["prog", "--dry-run"]):
            with patch("src.pipeline.main_pipeline") as mock_pipeline:
                from src.__main__ import main
                main()
                mock_pipeline.assert_called_once_with(dry_run=True)

    def test_default_no_flags_calls_main_pipeline_dry_run_false(self):
        with patch("sys.argv", ["prog"]):
            with patch("src.pipeline.main_pipeline") as mock_pipeline:
                from src.__main__ import main
                main()
                mock_pipeline.assert_called_once_with(dry_run=False)

    def test_promote_calls_promote_to_production(self):
        with patch("sys.argv", ["prog", "--promote"]):
            with patch("src.pipeline.promote_to_production") as mock_promote:
                from src.__main__ import main
                main()
                mock_promote.assert_called_once()

    def test_dry_run_and_promote_mutually_exclusive(self):
        with patch("sys.argv", ["prog", "--dry-run", "--promote"]):
            with pytest.raises(SystemExit) as exc:
                from src.__main__ import main
                main()
            assert exc.value.code == 1

    def test_scheduler_calls_run_scheduler(self):
        scheduler_mock = MagicMock()
        with patch.dict("sys.modules", {"src.scheduler": scheduler_mock}):
            with patch("sys.argv", ["prog", "--scheduler"]):
                from src.__main__ import main
                main()
                scheduler_mock.run_scheduler.assert_called_once_with(interval_days=7)

    def test_scheduler_with_custom_interval(self):
        scheduler_mock = MagicMock()
        with patch.dict("sys.modules", {"src.scheduler": scheduler_mock}):
            with patch("sys.argv", ["prog", "--scheduler", "--interval-days", "14"]):
                from src.__main__ import main
                main()
                scheduler_mock.run_scheduler.assert_called_once_with(interval_days=14)

    def test_pipeline_threshold_error_exits_with_code_1(self):
        with patch("sys.argv", ["prog"]):
            with patch("src.pipeline.main_pipeline", side_effect=PipelineThresholdError):
                with pytest.raises(SystemExit) as exc:
                    from src.__main__ import main
                    main()
                assert exc.value.code == 1

    def test_prints_summary_after_pipeline(self, capsys):
        with patch("sys.argv", ["prog"]):
            with patch("src.pipeline.main_pipeline", return_value={
                "scraped": 10, "enriched_count": 7, "kept_after_validation": 5,
                "rejected_duplicates": 2, "errors": 1, "invalid_records": 1, "elapsed": 3.2,
            }):
                from src.__main__ import main
                main()
                out = capsys.readouterr().out
        assert "Pipeline summary:" in out
        assert "scraped=10" in out
        assert "enriched=7" in out
        assert "kept=5" in out
        assert "rejected_dups=2" in out
        assert "errors=1" in out
        assert "invalid=1" in out
        assert "elapsed=3.2s" in out

    def test_prints_elapsed_with_question_mark_when_missing(self, capsys):
        with patch("sys.argv", ["prog"]):
            with patch("src.pipeline.main_pipeline", return_value={
                "scraped": 0, "enriched_count": 0, "kept_after_validation": 0,
                "rejected_duplicates": 0, "errors": 0, "invalid_records": 0,
            }):
                from src.__main__ import main
                main()
                out = capsys.readouterr().out
        assert "elapsed=?s" in out

    def test_mutually_exclusive_error_message(self, capsys):
        with patch("sys.argv", ["prog", "--dry-run", "--promote"]):
            from src.__main__ import main
            with pytest.raises(SystemExit):
                main()
            stderr = capsys.readouterr().err
            assert "mutually exclusive" in stderr
