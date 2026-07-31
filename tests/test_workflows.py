"""Feature 005 (US4 / FR-009, quickstart V10): scheduled run + config-pointer hygiene.

Static inspection of the GitHub Actions workflows — no live dispatch is attempted.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _read(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


class TestDailyScheduledRun:
    """SC-006 / FR-009 — weekdays 06:00 UTC cron plus manual dispatch."""

    def test_daily_workflow_has_weekday_cron(self):
        assert "0 6 * * 1-5" in _read("daily.yml")

    def test_daily_workflow_has_manual_dispatch(self):
        assert "workflow_dispatch" in _read("daily.yml")

    def test_daily_workflow_points_at_renamed_config(self):
        assert "config/targets.yaml" in _read("daily.yml")

    def test_scrape_workflow_points_at_renamed_config(self):
        assert "config/targets.yaml" in _read("scrape.yml")


class TestRetiredGateHygiene:
    """T020 — SCRAPE_FULL_PAGES and the old targets.yml path are fully removed."""

    def test_workflows_have_no_stale_gate_or_old_path(self):
        for name in ("daily.yml", "scrape.yml"):
            text = _read(name)
            assert "SCRAPE_FULL_PAGES" not in text, name
            assert "config/targets.yml" not in text, name

    def test_source_and_run_do_not_reference_stale_gate(self):
        candidates = []
        for path in (REPO_ROOT / "src", REPO_ROOT / "run.py"):
            if path.is_dir():
                candidates.extend(path.rglob("*.py"))
            else:
                candidates.append(path)
        for py in candidates:
            assert "SCRAPE_FULL_PAGES" not in py.read_text(encoding="utf-8"), py
