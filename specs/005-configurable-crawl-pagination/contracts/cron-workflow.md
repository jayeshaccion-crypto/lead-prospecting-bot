# Contract: cron-workflow

**Feature**: 005-configurable-crawl-pagination | **Spec**: [spec.md](../spec.md) FR-009, SC-006, Q3 | **Date**: 2026-07-31

## 1. Schedule (FR-009 / SC-006)

Exact cron syntax: **`0 6 * * 1-5`** — weekdays (Mon–Fri) at 06:00 UTC, which is 11:30 IST. Confirmed via clarification Q3.

## 2. `.github/workflows/daily.yml` — exact changes

Already present and retained:
```yaml
on:
  schedule:
    - cron: '0 6 * * 1-5'
  workflow_dispatch:
```

Required diffs in the Run/pipeline step's `env`:
- `TARGETS_CONFIG: config/targets.yml` → `TARGETS_CONFIG: config/targets.yaml` (file rename in this feature).
- **Remove** `SCRAPE_FULL_PAGES` (retired per FR-005/Q5 — a stale value is ignored anyway, but it is deleted to avoid confusion).
- `WRAP` block (masked secrets) unchanged.

## 3. `.github/workflows/scrape.yml` — exact changes

Weekly legacy workflow:
- Cron `0 6 * * 1` unchanged.
- **Add** `TARGETS_CONFIG: config/targets.yaml` to the pipeline step's `env` — after the file rename, without this the run falls back to the default `config/targets.yml`, which no longer exists, and would silently scrape 0 targets.
- Existing `SCRAPE_FULL_PAGES: ${{ vars.SCRAPE_FULL_PAGES }}` env is removed (retired gate).

## 4. Verification (spec User Story 4 Independent Test)

- Inspect `daily.yml`: `schedule.cron == '0 6 * * 1-5'` and `workflow_dispatch` present.
- Trigger `workflow_dispatch` to confirm an on-demand run executes between scheduled times.
- Confirm no workflow references `targets.yml` or `SCRAPE_FULL_PAGES` after the change (grep the `.github/workflows/` directory).
