"""Run the full lead prospecting pipeline: scrape all sites, enrich, write to local DB, build dashboard."""
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DB = Path("data") / "leads.db"


def lead_columns() -> list[str]:
    return [
        "company_name", "website", "email", "phone", "address",
        "industry_code", "employee_count", "revenue_band",
        "source_url", "scraped_at", "dedup_key", "lead_score",
    ]


def main():
    start = time.perf_counter()
    logger.info("Pipeline started")

    from src.scraper.engine import scrape_all_targets
    from src.scraper.targets import RawRecord

    # 1. Scrape all targets
    raw_records, errors = scrape_all_targets()
    logger.info("Scraped %d raw records, %d target errors", len(raw_records), len(errors))

    # 2. Convert to lead rows
    now = datetime.now(timezone.utc).isoformat()
    lead_rows = []
    for rec in raw_records:
        dedup_key = ""
        if rec.website:
            from urllib.parse import urlparse
            try:
                host = urlparse(rec.website).netloc.lower() or rec.website.lower()
                dedup_key = host.removeprefix("www.").split("/")[0]
            except Exception:
                dedup_key = rec.website.lower()
        lead_rows.append([
            rec.company_name, rec.website or "", rec.email or "", rec.phone or "",
            rec.address or "", rec.industry_code or "", "", "", rec.source_url or "",
            now, dedup_key, "",
        ])

    # 3. Write to local DB
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB))
    for table in ("staging", "scrape_errors", "rejected_duplicates", "Leads"):
        conn.execute(f"DELETE FROM [{table}]")
    conn.commit()

    cols = lead_columns()
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(f'"{h}"' for h in cols)
    conn.executemany(
        f"INSERT INTO Leads ({col_names}) VALUES ({placeholders})",
        lead_rows,
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM Leads").fetchone()[0]
    conn.close()
    logger.info("Written %d records to Leads table (%.1fs)", count, time.perf_counter() - start)

    # 4. Write to Neo4j graph database
    try:
        import neo4j
        from src.graphdb.client import upsert_company
        from src.graphdb import get_driver, close_driver
        driver = get_driver()
        for row in lead_rows:
            row_dict = dict(zip(lead_columns(), row))
            upsert_company(driver, row_dict)
        close_driver()
        logger.info("Written %d records to Neo4j", len(lead_rows))
    except Exception as exc:
        logger.warning("Neo4j write skipped (%s)", exc)

    # 5. Build dashboard
    import build_dashboard
    build_dashboard.build()
    graph_stats = "--"
    try:
        from src.graphdb import get_driver
        d = get_driver()
        from src.graphdb.client import get_stats
        s = get_stats(d)
        graph_stats = f"{s['Company']}C {s['Phone']}P {s['Email']}E"
        d.close()
    except Exception:
        pass
    logger.info("Dashboard rebuilt | Neo4j: %s (total %.1fs)", graph_stats, time.perf_counter() - start)


if __name__ == "__main__":
    main()
