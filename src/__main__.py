import argparse
import sys


def main():
    """Entry point for the lead prospecting pipeline CLI.

    Parses command-line arguments and dispatches to the appropriate
    subcommand (scheduler, promote, or pipeline run).
    """
    parser = argparse.ArgumentParser(description="Lead Prospecting Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Write to staging tab only")
    parser.add_argument("--promote", action="store_true", help="Copy staging rows to production tab")
    parser.add_argument("--scheduler", action="store_true", help="Start the APScheduler loop")
    parser.add_argument("--interval-days", type=int, default=7, help="Days between scheduled runs (default: 7)")
    args = parser.parse_args()

    if args.dry_run and args.promote:
        print("ERROR: --dry-run and --promote are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    if args.scheduler:
        from src.scheduler import run_scheduler
        run_scheduler(interval_days=args.interval_days)
    elif args.promote:
        from src.pipeline import promote_to_production
        promote_to_production()
    else:
        from src.pipeline import main_pipeline, PipelineThresholdError
        try:
            summary = main_pipeline(dry_run=args.dry_run)
            print(
                "Pipeline summary: "
                f"scraped={summary['scraped']} enriched={summary['enriched_count']} "
                f"kept={summary['kept_after_validation']} "
                f"rejected_dups={summary['rejected_duplicates']} "
                f"errors={summary['errors']} invalid={summary['invalid_records']} "
                f"elapsed={summary.get('elapsed', '?')}s",
            )
        except PipelineThresholdError:
            sys.exit(1)


if __name__ == "__main__":
    main()
