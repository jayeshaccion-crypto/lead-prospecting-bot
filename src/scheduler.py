import logging

from apscheduler.schedulers.blocking import BlockingScheduler

logger = logging.getLogger(__name__)


def run_pipeline_job():
    """Job function that runs the full pipeline, called by the scheduler."""
    from src.pipeline import main_pipeline, PipelineThresholdError

    logger.info("Scheduler triggered pipeline run")
    try:
        summary = main_pipeline(dry_run=False)
        logger.info("Scheduled pipeline completed: %s", summary)
    except PipelineThresholdError:
        logger.warning("Scheduled pipeline run aborted — threshold exceeded")
    except Exception:
        logger.exception("Scheduled pipeline run failed")


def run_scheduler(interval_days: int = 7):
    """Start the APScheduler loop that runs the pipeline on an interval.

    When interval_days is 7 (the default), uses a cron schedule for
    Monday 06:00 UTC. Non-default intervals use a simple interval trigger.

    Args:
        interval_days: Days between scheduled runs (default 7).
    """
    scheduler = BlockingScheduler()
    if interval_days == 7:
        scheduler.add_job(
            run_pipeline_job,
            trigger="cron",
            day_of_week="mon",
            hour=6,
            id="lead_pipeline",
            name="Lead Prospecting Pipeline (weekly)",
        )
        logger.info("Starting scheduler with cron schedule: Monday 06:00 UTC")
    else:
        scheduler.add_job(
            run_pipeline_job,
            trigger="interval",
            days=interval_days,
            id="lead_pipeline",
            name="Lead Prospecting Pipeline (every %d days)" % interval_days,
        )
        logger.info("Starting scheduler with interval=%d days", interval_days)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
