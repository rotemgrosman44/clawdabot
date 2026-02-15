# UNUSED_OR_DUPLICATE (Governance Canon Hygiene)

This file classifies unused, duplicate-intent, and legacy artifacts so operators can make safe cleanup decisions with evidence anchors.

Evidence anchors:

- Latest canon guard bundle: `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-latest/` (symlink created by Canon Guard runner)
- Mapping audit bundle: `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/gmail-arch-20260214T230718Z/`

## Duplicate-Intent Schedules (Must Stay Disabled)

These cron jobs duplicate systemd-authoritative intents and must remain disabled permanently:

- `gmail-plumber-daily` (duplicates systemd triage schedule)
- `newsletter-master-weekly` (duplicates systemd newsletter master schedule)
- `daily-morning-report` (duplicates MB schedule intent; non-canon)

Classification:

- Keep: **yes**
- State: **disabled forever**
- Rationale: prevents dual scheduler drift. See `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/docs/governance/canon/SCHEDULERS.md`.

## Legacy Newsletter Outputs (Deprecated)

Deprecated paths (flat outputs):

- `/home/rotemgrosman/jarvis-stack/jarvis-data/newsletter-weekly/message.txt`
- `/home/rotemgrosman/jarvis-stack/jarvis-data/newsletter-weekly/signals.json`
- `/home/rotemgrosman/jarvis-stack/jarvis-data/newsletter-weekly/report.json`
- `/home/rotemgrosman/jarvis-stack/jarvis-data/newsletter-weekly/report.md`

Classification:

- Keep: **no** (as real files)
- Replace with: symlinks into `/home/rotemgrosman/jarvis-stack/jarvis-data/newsletter-weekly/latest/*`
- Rationale: removes ambiguous contract; downstream consumers read only from `latest/*`.

## Unreferenced Scripts (Heuristic)

Canon Guard emits a heuristic dead-files report (evidence: `dead_files_report.*` under the latest canon guard bundle).

The following may be unreferenced by systemd/cron/import-heuristics and require human classification:

- `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/newsletter_weekly_pipeline.py`
  - Classification: **keep** (canon pipeline tool; used for archive+latest standard)
- `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/newsletter_weekly_probe.py`
  - Classification: **keep** (canon builder invoked by pipeline)
- `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/drive_publish_newsletter_weekly.py`
  - Classification: **keep** (external API tool; must remain operator-only; never run in governance checks)
- `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/gog_scope_matrix.py`
  - Classification: **keep** (audit tool; manual)
- `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/google_workspace_smoke.py`
  - Classification: **keep** (audit tool; manual)
- `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/canon_check.py`
  - Classification: **unknown** (requires follow-up: is it superseded by `ops/checks/canon_guard_run_all.py`?)

## What Is Authoritative

- Canon Guard evidence outputs:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-*/dead_files_report.*`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-*/scheduler_guard_report.*`
- Scheduler authority:
  - systemd timers for Gmail Plumber polling (triage, newsletter-weekly)
  - Gateway cron jobs for brief delivery

## What Is Derived

- This document’s classifications are operational annotations on top of Canon Guard’s evidence.

## What Must Stay Disabled

Duplicate-intent cron jobs (must remain disabled forever; Canon Guard MUST fail if enabled):

- `gmail-plumber-daily`
- `newsletter-master-weekly`
- `daily-morning-report`

## Sources

- Canon Guard baseline pointer:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-baseline`
- Canon Guard dead files report (within baseline bundle):
  - `dead_files_report.md`
- Canon Guard scheduler report (within baseline bundle):
  - `scheduler_guard_report.md`

## Verification

Run Canon Guard and inspect the dead files report:

```bash
orbctl run -m ubuntu -w /home/rotemgrosman/jarvis-stack/jarvis/clawdbot bash -lc '
cd ops/checks
python3 canon_guard_run_all.py
D=$(readlink -f /home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-latest)
sed -n \"1,240p\" \"$D/dead_files_report.md\"
'
```
