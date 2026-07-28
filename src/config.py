import os
from pathlib import Path

import yaml

TARGET_INDUSTRY_LIST = [
    "IT Services", "Software", "Technology", "SaaS", "Fintech",
    "Healthcare", "E-commerce", "Manufacturing", "Education",
    "Real Estate", "BFSI", "Telecom", "Pharmaceuticals", "Automobile",
    "Food & Beverages", "Textiles", "Logistics", "Agri-tech",
    "Ed-tech", "Health-tech",
]


def get_db_path() -> str:
    """Get the database file path from env or default."""
    return os.environ.get("DB_PATH", "data/leads.db")


def load_targets_config(path: str | None = None) -> list[dict]:
    """Load the YAML targets configuration file.

    Args:
        path: Path to the YAML config file. If None, uses TARGETS_CONFIG env
              var or defaults to 'config/targets.yml'.

    Returns:
        List of target config dicts, or empty list if file not found.
    """
    if path is None:
        path = os.environ.get("TARGETS_CONFIG", "config/targets.yml")
    config_file = Path(path)
    if not config_file.exists():
        print(f"WARNING: Targets config not found at {config_file}. No targets will be scraped.")
        return []
    with open(config_file) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return []
    result = data.get("targets", [])
    return result if isinstance(result, list) else []
