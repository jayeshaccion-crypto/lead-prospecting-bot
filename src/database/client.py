"""SQLite-based database client replacing Google Sheets for lead storage."""

import sqlite3
from pathlib import Path

_DB_PATH = Path("data") / "leads.db"


def get_default_db_path() -> Path:
    return _DB_PATH


def set_default_db_path(path: str | Path):
    global _DB_PATH
    _DB_PATH = Path(path)


class DatabaseClient:
    """SQLite client that mirrors the SheetsClient interface.

    Manages tables for leads, staging, scrape_errors, and rejected_duplicates.
    Compatible with Cloudflare D1 (same SQL dialect) for future migration.
    """

    TABLES = {
        "Leads": [
            "company_name TEXT", "website TEXT", "email TEXT", "phone TEXT",
            "address TEXT", "industry_code TEXT", "employee_count TEXT",
            "revenue_band TEXT", "source_url TEXT", "scraped_at TEXT",
            "dedup_key TEXT", "lead_score TEXT",
        ],
        "staging": [
            "company_name TEXT", "website TEXT", "email TEXT", "phone TEXT",
            "address TEXT", "industry_code TEXT", "employee_count TEXT",
            "revenue_band TEXT", "source_url TEXT", "scraped_at TEXT",
            "dedup_key TEXT", "lead_score TEXT",
        ],
        "scrape_errors": [
            "url TEXT", "timestamp TEXT", "error_type TEXT",
        ],
        "rejected_duplicates": [
            "dedup_key TEXT", "kept_company TEXT", "rejected_company TEXT",
            "reason TEXT", "timestamp TEXT",
        ],
    }

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else _DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        for table_name, columns in self.TABLES.items():
            col_defs = ", ".join(
                f'"{col.split()[0]}" {col.split(maxsplit=1)[1]}'
                for col in columns
            )
            self.conn.execute(
                f"CREATE TABLE IF NOT EXISTS [{table_name}] (rowid INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})"
            )
        self.conn.commit()

    def ensure_tab(self, tab_name: str, headers: list[str]) -> bool:
        created = False
        if tab_name not in self.TABLES:
            col_defs = ", ".join(f'"{h}" TEXT' for h in headers)
            self.conn.execute(
                f"CREATE TABLE IF NOT EXISTS [{tab_name}] (rowid INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})"
            )
            self.TABLES[tab_name] = [f"{h} TEXT" for h in headers]
            created = True
        else:
            cursor = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tab_name,)
            )
            if not cursor.fetchone():
                col_defs = ", ".join(f'"{col.split()[0]}" TEXT' for col in self.TABLES[tab_name])
                self.conn.execute(
                    f"CREATE TABLE [{tab_name}] (rowid INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})"
                )
                created = True
        if created:
            self.conn.commit()
        return created

    def clear_tab(self, tab_name: str):
        self.conn.execute(f"DELETE FROM [{tab_name}]")
        self.conn.commit()

    def append_rows(self, tab_name: str, rows: list[list]):
        if not rows:
            return
        placeholders = ", ".join("?" for _ in rows[0])
        self.conn.executemany(
            f"INSERT INTO [{tab_name}] VALUES (NULL, {placeholders})", rows
        )
        self.conn.commit()

    def get_all_rows(self, tab_name: str) -> list[list]:
        try:
            cursor = self.conn.execute(f"SELECT * FROM [{tab_name}]")
            rows = cursor.fetchall()
            return [list(row[1:]) for row in rows]
        except sqlite3.OperationalError:
            return []

    def read_existing_dedup_keys(self, tab_name: str) -> set[str]:
        try:
            cursor = self.conn.execute(f"SELECT dedup_key FROM [{tab_name}] WHERE dedup_key IS NOT NULL AND dedup_key != ''")
            return {row[0] for row in cursor.fetchall()}
        except sqlite3.OperationalError:
            return set()

    def append_if_not_duplicate(self, tab_name: str, rows: list[list], additional_tabs: list[str] | None = None) -> list[list]:
        existing_keys = self.read_existing_dedup_keys(tab_name)
        if additional_tabs:
            for tab in additional_tabs:
                existing_keys |= self.read_existing_dedup_keys(tab)
        written = []
        for row in rows:
            dedup_key = row[10] if len(row) > 10 and row[10] else None
            if dedup_key and dedup_key in existing_keys:
                continue
            written.append(row)
            if dedup_key:
                existing_keys.add(dedup_key)
        if written:
            self.append_rows(tab_name, written)
        return written

    def close(self):
        self.conn.close()


DEDUP_KEY_INDEX = 10


def filter_new_rows(rows: list[list], existing_keys: set[str], dedup_key_index: int = DEDUP_KEY_INDEX) -> list[list]:
    """Filter out rows whose dedup_key already exists in existing_keys.

    Also deduplicates rows within the same batch (skips duplicate keys seen
    earlier in the same batch). Does not mutate input lists.

    Args:
        rows: List of row lists.
        existing_keys: Set of dedup_key strings already in the database.
        dedup_key_index: Column index of the dedup_key in each row.

    Returns:
        List of rows that are new (dedup_key not in existing or seen in batch).
    """
    result = []
    seen_in_batch = set()
    for row in rows:
        if dedup_key_index < len(row) and row[dedup_key_index]:
            key = row[dedup_key_index]
            if key in existing_keys or key in seen_in_batch:
                continue
            seen_in_batch.add(key)
        result.append(row)
    return result
