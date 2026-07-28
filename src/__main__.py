import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Lead Prospecting Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Write to staging tab only")
    parser.add_argument("--promote", action="store_true", help="Copy staging rows to production tab")
    parser.add_argument("--scheduler", action="store_true", help="Start the APScheduler loop")
    parser.add_argument("--interval-days", type=int, default=7, help="Days between scheduled runs (default: 7)")
    args = parser.parse_args()

    if args.scheduler:
        from src.scheduler import run_scheduler
        run_scheduler(interval_days=args.interval_days)
    elif args.promote:
        from src.pipeline import promote_to_production
        promote_to_production()
    else:
        from src.pipeline import main_pipeline
        main_pipeline(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
