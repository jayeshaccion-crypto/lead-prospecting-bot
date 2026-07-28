import os
import sys
from pathlib import Path

import yaml


def load_env_or_fail(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        print(f"FATAL: Required environment variable {key} is not set. Aborting.", file=sys.stderr)
        sys.exit(1)
    return value


def decode_service_account_key() -> str:
    import base64
    raw = load_env_or_fail("GOOGLE_SA_KEY")
    return base64.b64decode(raw).decode("utf-8")


def load_enrichment_api_key() -> str:
    return load_env_or_fail("ENRICH_API_KEY")


def load_enrichment_base_url() -> str:
    return os.environ.get("ENRICHMENT_BASE_URL", "https://api.example.com")


def load_sheet_id() -> str:
    return load_env_or_fail("SHEET_ID")


TARGET_INDUSTRY_LIST = [
    "IT Services",
    "Software",
    "Technology",
    "SaaS",
    "Fintech",
    "Healthcare",
    "E-commerce",
    "Manufacturing",
    "Education",
    "Real Estate",
    "BFSI",
    "Telecom",
    "Pharmaceuticals",
    "Automobile",
    "Food & Beverages",
    "Textiles",
    "Logistics",
    "Agri-tech",
    "Ed-tech",
    "Health-tech",
]


def load_targets_config(path: str | None = None) -> list[dict]:
    if path is None:
        path = os.environ.get("TARGETS_CONFIG", "config/targets.yml")
    config_file = Path(path)
    if not config_file.exists():
        print(f"WARNING: Targets config not found at {config_file}. No targets will be scraped.", file=sys.stderr)
        return []
    with open(config_file) as f:
        data = yaml.safe_load(f)
    return data.get("targets", [])
