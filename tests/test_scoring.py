from src.models import LeadRecord
from src.scoring import compute_lead_score, score_record, score_all_records


class TestComputeLeadScore:
    def test_zero_when_none_match(self):
        score, breakdown = compute_lead_score()
        assert score == 10  # recency 'new' = +10

    def test_phone_only(self):
        score, breakdown = compute_lead_score(has_phone=True)
        assert score == 35  # 25 (phone) + 10 (recency new) = 35
        assert breakdown["has_phone"] == 25

    def test_email_only(self):
        score, breakdown = compute_lead_score(has_email=True)
        assert score == 25  # 15 (email) + 10 (recency new) = 25
        assert breakdown["has_email"] == 15

    def test_phone_and_email(self):
        score, _ = compute_lead_score(has_phone=True, has_email=True)
        assert score == 50  # 25+15+10 = 50

    def test_all_contact_fields(self):
        score, _ = compute_lead_score(has_phone=True, has_email=True, has_website=True)
        assert score == 65  # 25+15+15+10 = 65

    def test_multi_source_2_sites(self):
        score, breakdown = compute_lead_score(has_phone=True, multi_source_count=2)
        assert score == 60  # 25 (phone) + 25 (2 sites) + 10 (recency) = 60
        assert breakdown["source_score"] == 25
        assert breakdown["multi_source"] == "2_sites"

    def test_multi_source_all_3(self):
        score, breakdown = compute_lead_score(has_phone=True, multi_source_count=3)
        assert score == 70  # 25 (phone) + 35 (all 3) + 10 (recency) = 70
        assert breakdown["source_score"] == 35
        assert breakdown["multi_source"] == "all_3"

    def test_multi_source_single(self):
        score, breakdown = compute_lead_score(has_phone=True, multi_source_count=1)
        assert score == 35  # 25 + 0 + 10 = 35
        assert breakdown["source_score"] == 0

    def test_recency_new(self):
        score, breakdown = compute_lead_score(first_seen=None)
        assert breakdown["recency_score"] == 10
        assert breakdown["recency"] == "new"

    def test_icp_match(self):
        score, breakdown = compute_lead_score(is_icp_category=True)
        assert breakdown["icp_match"] == 10

    def test_icp_city_match(self):
        score, breakdown = compute_lead_score(is_icp_city=True)
        assert breakdown["icp_match"] == 10

    def test_no_icp_match(self):
        score, breakdown = compute_lead_score()
        assert breakdown["icp_match"] == 0

    def test_full_score_max(self):
        score, breakdown = compute_lead_score(
            has_phone=True, has_email=True, has_website=True,
            multi_source_count=3, is_icp_category=True,
        )
        assert score == 100  # 25+15+15+35+10 = 100
        assert score == min(score, 100)

    def test_caps_at_100(self):
        score, _ = compute_lead_score(
            has_phone=True, has_email=True, has_website=True,
            multi_source_count=3, is_icp_category=True, is_icp_city=True,
        )
        assert score == 100

    def test_deterministic_same_input(self):
        inputs = dict(has_phone=True, has_email=False, has_website=True, multi_source_count=2)
        results = [compute_lead_score(**inputs) for _ in range(10)]
        scores = {s for s, _ in results}
        assert len(scores) == 1
        breakdowns = [tuple(sorted(b.items())) for _, b in results]
        assert len(set(breakdowns)) == 1


class TestScoreRecord:
    def test_scores_lead_record_with_all_fields(self):
        record = LeadRecord(
            company_name="Acme Corp",
            email="contact@acme.com",
            phone="+1-555-0100",
            website="https://acme.com",
            sources=["IndiaMART"],
        )
        score, breakdown = score_record(record)
        assert isinstance(score, int)
        assert isinstance(breakdown, dict)
        assert breakdown["has_phone"] == 25
        assert breakdown["has_email"] == 15
        assert breakdown["has_website"] == 15

    def test_scores_record_with_no_data(self):
        record = LeadRecord(company_name="Acme Corp")
        score, breakdown = score_record(record)
        assert score == 10  # only recency new
        assert breakdown["contact"] == 0

    def test_email_prefix_UNVERIFIED_still_counts_as_email(self):
        record = LeadRecord(company_name="Acme Corp", email="UNVERIFIED:bademail")
        score, breakdown = score_record(record)
        assert breakdown["has_email"] == 15

    def test_none_email_and_none_phone(self):
        record = LeadRecord(company_name="Acme Corp", email=None, phone=None)
        score, breakdown = score_record(record)
        assert score == 10  # only recency new

    def test_with_icp_flags(self):
        record = LeadRecord(company_name="Acme Corp", phone="555", category_slug="software-development")
        score, _ = score_record(record, is_icp_cat=True)
        assert score == 45  # 25 (phone) + 10 (recency) + 10 (ICP) = 45


class TestScoreAllRecords:
    def test_empty_records_list(self):
        result = score_all_records([])
        assert result == []

    def test_single_record(self):
        records = [LeadRecord(company_name="Alpha", email="a@a.com")]
        result = score_all_records(records)
        assert result[0].lead_score == 25  # 15 (email) + 10 (recency) = 25

    def test_scores_multiple_records_in_place(self):
        records = [
            LeadRecord(company_name="Alpha", email="a@a.com"),
            LeadRecord(company_name="Beta"),
            LeadRecord(company_name="Gamma", phone="99999", website="https://gamma.com"),
        ]
        result = score_all_records(records)
        assert result is records
        assert records[0].lead_score == 25  # 15+10
        assert records[1].lead_score == 10  # only recency
        assert records[2].lead_score == 50  # 25 (phone) + 15 (website) + 10 (recency) = 50

    def test_with_icp_categories(self):
        records = [LeadRecord(company_name="Alpha", phone="555", category_slug="software-development")]
        result = score_all_records(records, icp_categories={"software-development"})
        assert records[0].lead_score == 45  # 25+10+10 = 45

    def test_icp_ignored_when_not_configured(self):
        records = [LeadRecord(company_name="Alpha", phone="555", category_slug="software-development")]
        result = score_all_records(records)
        assert records[0].lead_score == 35  # 25+10 = 35, ICP not configured
