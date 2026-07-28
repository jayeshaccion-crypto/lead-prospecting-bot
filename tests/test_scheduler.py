import logging
from unittest.mock import MagicMock, patch

import pytest

import src.scheduler as scheduler_mod


class TestRunPipelineJob:
    def test_success_path(self, caplog):
        caplog.set_level(logging.INFO)
        with patch("src.pipeline.main_pipeline", return_value={"scraped": 5}) as mock_pipeline:
            scheduler_mod.run_pipeline_job()
            mock_pipeline.assert_called_once_with(dry_run=False)
        assert any("Scheduler triggered pipeline run" in r.message for r in caplog.records)
        assert any("Scheduled pipeline completed" in r.message for r in caplog.records)

    def test_pipeline_threshold_error(self, caplog):
        caplog.set_level(logging.WARNING)
        from src.pipeline import PipelineThresholdError
        with patch("src.pipeline.main_pipeline", side_effect=PipelineThresholdError):
            scheduler_mod.run_pipeline_job()
        assert any("threshold exceeded" in r.message for r in caplog.records if r.levelname == "WARNING")

    def test_generic_exception(self, caplog):
        caplog.set_level(logging.ERROR)
        with patch("src.pipeline.main_pipeline", side_effect=RuntimeError("boom")):
            scheduler_mod.run_pipeline_job()
        assert any("Scheduled pipeline run failed" in r.message for r in caplog.records if r.levelname == "ERROR")


class TestRunScheduler:
    def test_uses_cron_when_seven_days(self):
        with patch.object(scheduler_mod, "BlockingScheduler") as scheduler_cls:
            scheduler_instance = scheduler_cls.return_value
            scheduler_mod.run_scheduler(interval_days=7)
        scheduler_instance.add_job.assert_called_once()
        call_kwargs = scheduler_instance.add_job.call_args[1]
        assert call_kwargs["trigger"] == "cron"
        assert call_kwargs["day_of_week"] == "mon"
        assert call_kwargs["hour"] == 6
        assert call_kwargs["id"] == "lead_pipeline"

    def test_uses_interval_when_not_seven_days(self):
        with patch.object(scheduler_mod, "BlockingScheduler") as scheduler_cls:
            scheduler_instance = scheduler_cls.return_value
            scheduler_mod.run_scheduler(interval_days=14)
        scheduler_instance.add_job.assert_called_once()
        call_kwargs = scheduler_instance.add_job.call_args[1]
        assert call_kwargs["trigger"] == "interval"
        assert call_kwargs["days"] == 14

    def test_uses_interval_when_one_day(self):
        with patch.object(scheduler_mod, "BlockingScheduler") as scheduler_cls:
            scheduler_instance = scheduler_cls.return_value
            scheduler_mod.run_scheduler(interval_days=1)
        scheduler_instance.add_job.assert_called_once()
        call_kwargs = scheduler_instance.add_job.call_args[1]
        assert call_kwargs["trigger"] == "interval"
        assert call_kwargs["days"] == 1

    def test_calls_start(self):
        with patch.object(scheduler_mod, "BlockingScheduler") as scheduler_cls:
            scheduler_instance = scheduler_cls.return_value
            scheduler_mod.run_scheduler(interval_days=7)
        scheduler_instance.start.assert_called_once()

    def test_keyboard_interrupt_caught(self):
        with patch.object(scheduler_mod, "BlockingScheduler") as scheduler_cls:
            scheduler_instance = scheduler_cls.return_value
            scheduler_instance.start.side_effect = KeyboardInterrupt()
            scheduler_mod.run_scheduler(interval_days=7)
        scheduler_instance.start.assert_called_once()

    def test_system_exit_caught(self):
        with patch.object(scheduler_mod, "BlockingScheduler") as scheduler_cls:
            scheduler_instance = scheduler_cls.return_value
            scheduler_instance.start.side_effect = SystemExit()
            scheduler_mod.run_scheduler(interval_days=7)
        scheduler_instance.start.assert_called_once()

    def test_logs_cron_schedule(self, caplog):
        caplog.set_level(logging.INFO)
        with patch.object(scheduler_mod, "BlockingScheduler"):
            scheduler_mod.run_scheduler(interval_days=7)
        assert any("cron schedule: Monday 06:00 UTC" in r.message for r in caplog.records if r.levelname == "INFO")

    def test_logs_interval_schedule(self, caplog):
        caplog.set_level(logging.INFO)
        with patch.object(scheduler_mod, "BlockingScheduler"):
            scheduler_mod.run_scheduler(interval_days=3)
        assert any("interval=3 days" in r.message for r in caplog.records if r.levelname == "INFO")
