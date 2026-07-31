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
    data = load_full_config(path)
    if not data:
        return []
    result = data.get("targets", [])
    return result if isinstance(result, list) else []


def load_full_config(path: str | None = None) -> dict:
    """Load the full YAML configuration dict.

    Args:
        path: Path to the YAML config file.

    Returns:
        The full parsed config dict, or empty dict if not found.
    """
    if path is None:
        path = os.environ.get("TARGETS_CONFIG", "config/targets.yml")
    config_file = Path(path)
    if not config_file.exists():
        print(f"WARNING: Targets config not found at {config_file}. No targets will be scraped.")
        return {}
    with open(config_file) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return {}
    return data


def get_icp_categories(config: dict | None = None) -> set[str]:
    """Return the set of ICP category slugs from config."""
    if config is None:
        config = load_full_config()
    icp = config.get("icp", {})
    if isinstance(icp, dict):
        cats = icp.get("categories", [])
        if isinstance(cats, list):
            return {c["slug"] if isinstance(c, dict) else str(c) for c in cats}
    return set()


def get_icp_cities(config: dict | None = None) -> set[str]:
    """Return the set of ICP city slugs from config."""
    if config is None:
        config = load_full_config()
    icp = config.get("icp", {})
    if isinstance(icp, dict):
        cities = icp.get("cities", [])
        if isinstance(cities, list):
            return {c["slug"] if isinstance(c, dict) else str(c) for c in cities}
    return set()
