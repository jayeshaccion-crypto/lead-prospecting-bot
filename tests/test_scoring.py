import pytest

from src.models import LeadRecord
from src.scoring import compute_lead_score, score_record, score_all_records


class TestComputeLeadScore:
    def test_zero_when_none_match(self):
        assert compute_lead_score(has_email=False, has_phone=False, employee_count=None, industry_code=None) == 0

    def test_email_only(self):
        assert compute_lead_score(has_email=True, has_phone=False, employee_count=None, industry_code=None) == 40

    def test_phone_only(self):
        assert compute_lead_score(has_email=False, has_phone=True, employee_count=None, industry_code=None) == 20

    def test_email_and_phone(self):
        assert compute_lead_score(has_email=True, has_phone=True, employee_count=None, industry_code=None) == 60

    def test_size_fit_mid_range(self):
        assert compute_lead_score(has_email=False, has_phone=False, employee_count=100, industry_code=None) == 20

    def test_size_fit_low_boundary(self):
        assert compute_lead_score(has_email=False, has_phone=False, employee_count=10, industry_code=None) == 20

    def test_size_fit_high_boundary(self):
        assert compute_lead_score(has_email=False, has_phone=False, employee_count=500, industry_code=None) == 20

    def test_size_too_small(self):
        assert compute_lead_score(has_email=False, has_phone=False, employee_count=9, industry_code=None) == 0

    def test_size_too_large(self):
        assert compute_lead_score(has_email=False, has_phone=False, employee_count=501, industry_code=None) == 0

    def test_industry_match(self):
        assert compute_lead_score(
            has_email=False, has_phone=False, employee_count=None, industry_code="Software"
        ) == 20

    def test_industry_no_match(self):
        assert compute_lead_score(
            has_email=False, has_phone=False, employee_count=None, industry_code="Agriculture"
        ) == 0

    def test_all_factors(self):
        score = compute_lead_score(
            has_email=True, has_phone=True, employee_count=250, industry_code="Software"
        )
        assert score == 100
        assert score == 40 + 20 + 20 + 20

    def test_caps_at_100(self):
        score = compute_lead_score(
            has_email=True, has_phone=True, employee_count=250, industry_code="Software"
        )
        assert score == 100

    def test_custom_industry_list(self):
        custom = ["Marine", "Aerospace"]
        score = compute_lead_score(
            has_email=False, has_phone=False, employee_count=None, industry_code="Software",
            target_industries=custom,
        )
        assert score == 0
        score = compute_lead_score(
            has_email=False, has_phone=False, employee_count=None, industry_code="Marine",
            target_industries=custom,
        )
        assert score == 20

    def test_deterministic_same_input(self):
        inputs = dict(has_email=True, has_phone=False, employee_count=50, industry_code="Fintech")
        scores = {compute_lead_score(**inputs) for _ in range(10)}
        assert len(scores) == 1

    def test_employee_count_none(self):
        assert compute_lead_score(has_email=False, has_phone=False, employee_count=None, industry_code=None) == 0


class TestScoreRecord:
    def test_scores_lead_record(self):
        record = LeadRecord(
            company_name="Acme Corp",
            email="contact@acme.com",
            phone="+1-555-0100",
            employee_count=100,
            industry_code="Software",
        )
        score = score_record(record)
        assert score == 100

    def test_scores_record_with_no_data(self):
        record = LeadRecord(company_name="Acme Corp")
        score = score_record(record)
        assert score == 0

    def test_email_prefix_UNVERIFIED_still_counts_as_email(self):
        record = LeadRecord(company_name="Acme Corp", email="UNVERIFIED:bademail")
        score = score_record(record)
        assert score == 40  # has_email=True because bool("UNVERIFIED:...") is True


class TestScoreRecordEdgeCases:
    def test_none_email_and_none_phone(self):
        record = LeadRecord(company_name="Acme Corp", email=None, phone=None)
        assert score_record(record) == 0

    def test_empty_email_empty_phone(self):
        record = LeadRecord(company_name="Acme Corp", email="", phone="")
        assert score_record(record) == 0

    def test_only_employee_count_no_industry(self):
        record = LeadRecord(company_name="Acme Corp", employee_count=100)
        assert score_record(record) == 20

    def test_only_industry_no_employee(self):
        record = LeadRecord(company_name="Acme Corp", industry_code="Software")
        assert score_record(record) == 20

    def test_negative_employee_count(self):
        record = LeadRecord(company_name="Acme Corp", email="a@a.com", phone="555", employee_count=-5, industry_code="Agriculture")
        assert score_record(record) == 60  # email(40) + phone(20), size(-5) excluded, Agriculture not in target list


class TestScoreAllRecords:
    def test_empty_records_list(self):
        result = score_all_records([])
        assert result == []

    def test_single_record(self):
        records = [LeadRecord(company_name="Alpha", email="a@a.com")]
        result = score_all_records(records)
        assert result[0].lead_score == 40

    def test_scores_multiple_records_in_place(self):
        records = [
            LeadRecord(company_name="Alpha", email="a@a.com"),
            LeadRecord(company_name="Beta"),
            LeadRecord(company_name="Gamma", phone="+91-99999", employee_count=50, industry_code="IT Services"),
        ]
        result = score_all_records(records)
        expected_gamma = 20 + 20 + 20  # phone + size(50) + industry("IT Services")
        assert result is records
        assert records[0].lead_score == 40
        assert records[1].lead_score == 0
        assert records[2].lead_score == expected_gamma
