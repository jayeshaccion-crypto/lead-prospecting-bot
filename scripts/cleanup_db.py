"""Database cleanup script for lead-prospecting-bot.

Safe to run in GitHub Actions when manual cleanup is required.
Provides dry-run mode and targeted table clearing.

Usage:
    python scripts/cleanup_db.py --staging          # Clear staging only
    python scripts/cleanup_db.py --errors           # Clear scrape_errors
    python scripts/cleanup_db.py --rejected         # Clear rejected_duplicates
    python scripts/cleanup_db.py --leads            # Clear Leads (DESTRUCTIVE)
    python scripts/cleanup_db.py --reset            # Clear all data tables
    python scripts/cleanup_db.py --vacuum           # Shrink DB file
    python scripts/cleanup_db.py --reset --dry-run  # Preview without deleting
    python scripts/cleanup_db.py --help             # Show this message
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DB = Path("data") / "leads.db"

TABLES = ["Leads", "staging", "scrape_errors", "rejected_duplicates"]


def table_row_count(cur: sqlite3.Cursor, table: str) -> int:
    try:
        cur.execute(f"SELECT COUNT(*) FROM [{table}]")
        return cur.fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def main():
    parser = argparse.ArgumentParser(description="Cleanup the lead database", add_help=False)
    parser.add_argument("--leads", action="store_true", help="Clear the Leads table (DESTRUCTIVE)")
    parser.add_argument("--staging", action="store_true", help="Clear the staging table")
    parser.add_argument("--errors", action="store_true", help="Clear scrape_errors table")
    parser.add_argument("--rejected", action="store_true", help="Clear rejected_duplicates table")
    parser.add_argument("--reset", action="store_true", help="Clear all data tables")
    parser.add_argument("--vacuum", action="store_true", help="Reclaim disk space (VACUUM)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    parser.add_argument("--help", action="store_true", help="Show usage and exit")
    args = parser.parse_args()

    if args.help or not any([args.leads, args.staging, args.errors, args.rejected, args.reset, args.vacuum]):
        print(__doc__)
        sys.exit(0 if args.help else 1)

    if not DB.exists():
        print(f"Database not found at {DB.resolve()} — nothing to do")
        return

    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()

    if args.reset:
        args.leads = args.staging = args.errors = args.rejected = True

    targets = []
    if args.leads:
        targets.append("Leads")
    if args.staging:
        targets.append("staging")
    if args.errors:
        targets.append("scrape_errors")
    if args.rejected:
        targets.append("rejected_duplicates")

    if targets:
        print("Target  | Rows")
        print("-" * 20)
        total = 0
        for t in targets:
            count = table_row_count(cur, t)
            print(f"{t:<14} {count}")
            total += count
            if not args.dry_run:
                cur.execute(f"DELETE FROM [{t}]")
        print("-" * 20)
        print(f"{'TOTAL':<14} {total}")
        if args.dry_run:
            print(f"\nDry-run — {total} rows would be deleted. Run without --dry-run to execute.")
        else:
            conn.commit()
            print(f"\nDeleted {total} rows across {len(targets)} table(s)")

    if args.vacuum:
        before = DB.stat().st_size
        if args.dry_run:
            print(f"Would VACUUM — currently {before / 1024:.1f} KB")
        else:
            cur.execute("VACUUM")
            after = DB.stat().st_size
            saved = before - after
            print(f"VACUUM complete: {before / 1024:.1f} KB → {after / 1024:.1f} KB (saved {saved / 1024:.1f} KB)")

    conn.close()


if __name__ == "__main__":
    main()
