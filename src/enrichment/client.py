import logging

import httpx

from src.config import load_enrichment_api_key, load_enrichment_base_url

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0


class EnrichmentClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = (base_url or load_enrichment_base_url()).rstrip("/")
        self.api_key = api_key or load_enrichment_api_key()
        self.timeout = timeout

    def get_enrichment(self, domain: str) -> dict:
        url = f"{self.base_url}/enrich"
        params = {"domain": domain}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, params=params, headers=headers)
            if response.status_code != 200:
                logger.warning("Enrichment API returned %s for domain %s", response.status_code, domain)
                return {}
            data = response.json()
            return {
                "employee_count": data.get("employee_count"),
                "revenue_band": data.get("revenue_band"),
            }
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning("Enrichment request failed for domain %s: %s", domain, exc)
            return {}
        except ValueError as exc:
            logger.warning("Enrichment API returned non-JSON body for domain %s: %s", domain, exc)
            return {}

    def enrich_many(self, domains: list[str]) -> dict[str, dict]:
        seen: dict[str, dict] = {}
        for domain in domains:
            if domain not in seen:
                seen[domain] = self.get_enrichment(domain)
        return seen


def enrich_records(records: list, base_url: str | None = None, api_key: str | None = None) -> list:
    client = EnrichmentClient(base_url=base_url, api_key=api_key)
    domains = list({r.dedup_key for r in records if r.dedup_key})
    if not domains:
        logger.info("No unique domains to enrich — all records missing dedup_key")
        return records
    enrichment_map = client.enrich_many(domains)
    enriched_count = 0
    for record in records:
        if record.dedup_key and record.dedup_key in enrichment_map:
            data = enrichment_map[record.dedup_key]
            if data.get("employee_count") is not None:
                record.employee_count = data["employee_count"]
                enriched_count += 1
            if data.get("revenue_band") is not None:
                record.revenue_band = data["revenue_band"]
    logger.info("Enriched %d/%d records across %d unique domains", enriched_count, len(records), len(domains))
    return records
