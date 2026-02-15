# ARTIFACTS (Governance Canon)

This document defines canonical vs derived artifacts for the Gmail Plumber subsystem, plus retention rules.

## Canonical Ledger (SoT local)

Append-only historical ledger:

- `/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports/`

File patterns:

- `gmail-triage-*.json` (triage runs)
- `newsletter-weekly-*.json` (newsletter master runs)

Retention:

- **Accumulate** (append-only). Do not overwrite. Prune only via an explicit retention policy change.

## Derived Products (Overwrite Allowed)

These are deterministic brief products. They are not the historical ledger.

- Morning brief:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/morning-brief/message.txt`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/morning-brief/signals.json`
  - Retention: overwrite per run

- End-of-day:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/eod/message.txt`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/eod/signals.json`
  - Retention: overwrite per run

- Weekly TOP-3:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/weekly-top3/message.txt`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/weekly-top3/signals.json`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/weekly-top3/report.json`
  - Retention: overwrite per run

## Newsletter Weekly (Standard: Archive + Latest Symlink)

Canonical layout (binding):

- Archive:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/archive/newsletter-weekly/YYYY/MM/week-YYYY-WW/run-YYYYMMDDTHHMMSS/`
- Latest pointer:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/newsletter-weekly/latest` (symlink to a run dir)

Required files per run dir:

- `telegram_message.txt` (exact line contract)
- `report.json` (items[] and top3[])
- `report.md` (Hebrew, RTL-safe)
- `signals.json`
- `evidence.json` (inputs read; upstream report path/id)

Legacy flat directory:

- `/home/rotemgrosman/jarvis-stack/jarvis-data/newsletter-weekly/` (flat `message.txt`, etc)

Policy:

- Flat outputs are **deprecated**.
- During migration, they must be removed or replaced by symlink(s) to `latest` outputs.

## Audit Bundles (Evidence-First)

All governance checks and mappings must emit evidence bundles under:

- `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/`

Example:

- `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/gmail-arch-20260214T230718Z/`

## What Is Authoritative

- Canonical historical ledger:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports/`
- Newsletter weekly canonical standard (archive + latest):
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/archive/newsletter-weekly/`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/newsletter-weekly/latest`

## What Is Derived

- Brief products (overwrite allowed):
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/morning-brief/`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/eod/`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/weekly-top3/`
- Audit bundles (evidence-only outputs):
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/`

## What Must Stay Disabled

Duplicate-intent cron jobs (must remain disabled forever; Canon Guard MUST fail if enabled):

- `gmail-plumber-daily`
- `newsletter-master-weekly`
- `daily-morning-report`

## Sources

- Canon Guard baseline pointer:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-baseline`
- Canon Guard artifact contract report (within baseline bundle):
  - `artifacts_contract_report.md`
- Newsletter weekly pipeline:
  - `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/newsletter_weekly_pipeline.py`

## Verification

Run Canon Guard and inspect the artifacts contract report:

```bash
orbctl run -m ubuntu -w /home/rotemgrosman/jarvis-stack/jarvis/clawdbot bash -lc '
cd ops/checks
python3 canon_guard_run_all.py
D=$(readlink -f /home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-latest)
sed -n \"1,200p\" \"$D/artifacts_contract_report.md\"
'
```
