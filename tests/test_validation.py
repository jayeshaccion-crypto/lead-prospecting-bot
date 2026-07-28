import sys
from unittest.mock import MagicMock

import pytest

sys.modules["google"] = MagicMock()
sys.modules["google.oauth2"] = MagicMock()
sys.modules["google.oauth2.service_account"] = MagicMock()
sys.modules["googleapiclient"] = MagicMock()
sys.modules["googleapiclient.discovery"] = MagicMock()

from src.models import LeadRecord
from src.validation import validate_record, filter_valid_records, InvalidRecord


def _make_record(**kwargs) -> LeadRecord:
    defaults = dict(company_name="Test", email="a@a.com", phone="555")
    defaults.update(kwargs)
    return LeadRecord.model_construct(**defaults)


class TestValidateRecord:
    def test_valid_record_with_email_and_phone_passes(self):
        record = _make_record()
        is_valid, reason = validate_record(record)
        assert is_valid is True
        assert reason is None

    def test_rejects_empty_company_name(self):
        record = _make_record(company_name="")
        is_valid, reason = validate_record(record)
        assert is_valid is False
        assert "company_name" in reason.lower()

    def test_rejects_whitespace_only_company_name(self):
        record = _make_record(company_name="   ")
        is_valid, reason = validate_record(record)
        assert is_valid is False

    def test_rejects_missing_both_email_and_phone(self):
        record = _make_record(email=None, phone=None)
        is_valid, reason = validate_record(record)
        assert is_valid is False
        assert "email" in reason.lower() and "phone" in reason.lower()

    def test_rejects_none_email_and_none_phone(self):
        record = _make_record(email=None, phone=None)
        is_valid, reason = validate_record(record)
        assert is_valid is False

    def test_accepts_email_only(self):
        record = _make_record(phone=None)
        is_valid, reason = validate_record(record)
        assert is_valid is True

    def test_accepts_phone_only(self):
        record = _make_record(email=None)
        is_valid, reason = validate_record(record)
        assert is_valid is True

    def test_validate_record_does_not_mutate_email(self):
        record = _make_record(email="bad-email")
        original_email = record.email
        is_valid, reason = validate_record(record)
        assert is_valid is True
        assert record.email == original_email

    def test_rejects_none_company_name(self):
        record = _make_record(company_name=None)
        is_valid, reason = validate_record(record)
        assert is_valid is False
        assert reason == "Empty company_name"

    def test_rejects_all_fields_none(self):
        record = _make_record(company_name=None, email=None, phone=None)
        is_valid, reason = validate_record(record)
        assert is_valid is False
        assert reason == "Empty company_name"

    def test_rejects_all_fields_empty_string(self):
        record = _make_record(company_name="", email="", phone="")
        is_valid, reason = validate_record(record)
        assert is_valid is False
        assert reason == "Empty company_name"

    def test_rejects_empty_email_and_none_phone(self):
        record = _make_record(email="", phone=None)
        is_valid, reason = validate_record(record)
        assert is_valid is False
        assert reason == "Missing both email and phone"

    def test_rejects_none_email_and_empty_phone(self):
        record = _make_record(email=None, phone="")
        is_valid, reason = validate_record(record)
        assert is_valid is False
        assert reason == "Missing both email and phone"


class TestFilterValidRecords:
    def test_all_valid_passes_through(self):
        records = [
            _make_record(company_name="A"),
            _make_record(company_name="B", email=None),
        ]
        valid, invalid = filter_valid_records(records)
        assert len(valid) == 2
        assert len(invalid) == 0

    def test_invalid_records_separated(self):
        records = [
            _make_record(company_name="A"),
            _make_record(company_name="", email="b@b.com", phone="555"),
            _make_record(company_name="C", email=None, phone=None),
        ]
        valid, invalid = filter_valid_records(records)
        assert len(valid) == 1
        assert len(invalid) == 2
        assert invalid[0].reason is not None
        assert invalid[1].reason is not None

    def test_invalid_records_have_reasons(self):
        records = [
            _make_record(company_name=""),
        ]
        valid, invalid = filter_valid_records(records)
        assert len(invalid) == 1
        assert invalid[0].reason == "Empty company_name"

    def test_empty_list_returns_empty(self):
        valid, invalid = filter_valid_records([])
        assert valid == []
        assert invalid == []

    def test_invalid_email_prefixed_still_valid(self):
        original_email = "bad-email"
        records = [
            _make_record(email=original_email),
        ]
        valid, invalid = filter_valid_records(records)
        assert len(valid) == 1
        assert valid[0].email == "UNVERIFIED:bad-email"
        assert records[0].email == original_email
        assert len(invalid) == 0

    def test_valid_email_not_prefixed(self):
        records = [
            _make_record(email="good@example.com"),
        ]
        valid, invalid = filter_valid_records(records)
        assert len(valid) == 1
        assert valid[0].email == "good@example.com"

    def test_multiple_invalid_emails_all_prefixed(self):
        records = [
            _make_record(company_name="A", email="bad1"),
            _make_record(company_name="B", email="bad2"),
        ]
        valid, invalid = filter_valid_records(records)
        assert len(valid) == 2
        assert valid[0].email == "UNVERIFIED:bad1"
        assert valid[1].email == "UNVERIFIED:bad2"

    def test_mixed_valid_and_invalid(self):
        records = [
            _make_record(company_name="Valid"),
            _make_record(company_name="NoContact", email=None, phone=None),
            _make_record(company_name="", email="x@x.com", phone="555"),
            _make_record(company_name="GoodPhone", email=None),
        ]
        valid, invalid = filter_valid_records(records)
        assert len(valid) == 2
        assert len(invalid) == 2

    def test_rejects_none_company_name(self):
        record = _make_record(company_name=None)
        valid, invalid = filter_valid_records([record])
        assert len(valid) == 0
        assert len(invalid) == 1
        assert invalid[0].reason == "Empty company_name"

    def test_rejects_empty_string_email_and_empty_string_phone(self):
        record = _make_record(email="", phone="")
        valid, invalid = filter_valid_records([record])
        assert len(valid) == 0
        assert len(invalid) == 1
        assert "email" in invalid[0].reason.lower()

    def test_accepts_empty_string_email_with_valid_phone(self):
        record = _make_record(email="", phone="555")
        valid, invalid = filter_valid_records([record])
        assert len(valid) == 1
        assert len(invalid) == 0

    def test_rejects_whitespace_only_phone_without_email(self):
        record = _make_record(email=None, phone="   ")
        valid, invalid = filter_valid_records([record])
        assert len(valid) == 0
        assert len(invalid) == 1
        assert invalid[0].reason == "Missing both email and phone"

    def test_rejects_whitespace_only_email_prefixes_it(self):
        record = _make_record(email="   ", phone="555")
        valid, invalid = filter_valid_records([record])
        assert len(valid) == 1
        assert valid[0].email == "UNVERIFIED:"
        assert len(invalid) == 0

    def test_accepts_none_phone_with_email(self):
        record = _make_record(phone=None)
        valid, invalid = filter_valid_records([record])
        assert len(valid) == 1
        assert len(invalid) == 0

    def test_logger_warning_called_for_invalid(self, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        records = [
            _make_record(company_name=""),
            _make_record(company_name="Bad", email=None, phone=None),
        ]
        filter_valid_records(records)
        assert len(caplog.records) == 2
        assert all(r.levelname == "WARNING" for r in caplog.records)
        assert "rejected by validation" in caplog.records[0].message
        assert "Empty company_name" in caplog.records[0].message
        assert "Missing both email and phone" in caplog.records[1].message

    def test_logger_info_summary_always_logged(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        records = [
            _make_record(company_name="A"),
            _make_record(company_name="B"),
        ]
        filter_valid_records(records)
        info_messages = [r.message for r in caplog.records if r.levelname == "INFO"]
        assert any(msg.startswith("Validation:") and "2 valid" in msg for msg in info_messages)

    def test_logger_info_summary_shows_invalid_count(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        records = [
            _make_record(company_name="A"),
            _make_record(company_name=""),
        ]
        filter_valid_records(records)
        info_messages = [r.message for r in caplog.records if r.levelname == "INFO"]
        assert any("1 valid, 1 invalid" in msg for msg in info_messages)

    def test_all_records_invalid(self):
        records = [
            _make_record(company_name=""),
            _make_record(company_name="B", email=None, phone=None),
        ]
        valid, invalid = filter_valid_records(records)
        assert len(valid) == 0
        assert len(invalid) == 2

    def test_does_not_mutate_input_list(self):
        records = [
            _make_record(company_name="A", email="bad-email"),
            _make_record(company_name="B"),
        ]
        original_emails = [(r.company_name, r.email) for r in records]
        filter_valid_records(records)
        for record, (orig_name, orig_email) in zip(records, original_emails):
            assert record.company_name == orig_name
            assert record.email == orig_email

    def test_logger_no_warnings_when_all_valid(self, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        records = [
            _make_record(company_name="A"),
            _make_record(company_name="B", email=None),
        ]
        filter_valid_records(records)
        assert len(caplog.records) == 0

    def test_valid_list_contains_only_valid(self):
        records = [
            _make_record(company_name="ValidA"),
            _make_record(company_name="", email="x@x.com", phone="555"),
            _make_record(company_name="ValidB", email=None),
            _make_record(company_name="C", email=None, phone=None),
        ]
        valid, invalid = filter_valid_records(records)
        valid_names = {r.company_name for r in valid}
        assert "ValidA" in valid_names
        assert "ValidB" in valid_names
        assert valid_names == {"ValidA", "ValidB"}

    def test_rejects_none_email_and_empty_phone(self):
        record = _make_record(email=None, phone="")
        valid, invalid = filter_valid_records([record])
        assert len(valid) == 0
        assert len(invalid) == 1
        assert invalid[0].reason == "Missing both email and phone"

    def test_rejects_empty_email_and_none_phone(self):
        record = _make_record(email="", phone=None)
        valid, invalid = filter_valid_records([record])
        assert len(valid) == 0
        assert len(invalid) == 1
        assert invalid[0].reason == "Missing both email and phone"

    def test_rejects_all_fields_none(self):
        record = _make_record(company_name=None, email=None, phone=None)
        valid, invalid = filter_valid_records([record])
        assert len(valid) == 0
        assert len(invalid) == 1
        assert invalid[0].reason == "Empty company_name"

    def test_rejects_all_fields_empty_string(self):
        record = _make_record(company_name="", email="", phone="")
        valid, invalid = filter_valid_records([record])
        assert len(valid) == 0
        assert len(invalid) == 1
        assert invalid[0].reason == "Empty company_name"


class TestInvalidRecord:
    def test_is_namedtuple(self):
        assert issubclass(InvalidRecord, tuple)

    def test_fields_accessible_by_name(self):
        record = _make_record(company_name="Bad", email=None, phone=None)
        ir = InvalidRecord(record=record, reason="Missing both email and phone")
        assert ir.record is record
        assert ir.reason == "Missing both email and phone"

    def test_iterable_as_tuple(self):
        record = _make_record(company_name="Bad")
        ir = InvalidRecord(record=record, reason="Empty company_name")
        unpacked_record, unpacked_reason = ir
        assert unpacked_record is record
        assert unpacked_reason == "Empty company_name"
