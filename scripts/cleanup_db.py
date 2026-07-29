"""Database cleanup — clears leads and rebuilds dashboard."""
import sqlite3
import subprocess
import sys
from pathlib import Path

DB = Path("data") / "leads.db"


def main():
    if not DB.exists():
        print(f"Nothing to clean — {DB} not found")
        return

    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()

    for table in ("staging", "scrape_errors", "rejected_duplicates", "Leads"):
        cur.execute(f"DELETE FROM [{table}]")
        print(f"Cleared {table}")

    conn.commit()
    conn.close()

    print(f"Database cleaned ({DB.stat().st_size / 1024:.1f} KB)")

    result = subprocess.run([sys.executable, "build_dashboard.py"], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print("Dashboard rebuild failed:", result.stderr)


if __name__ == "__main__":
    main()
