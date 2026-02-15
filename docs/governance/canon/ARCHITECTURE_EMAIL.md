# ARCHITECTURE_EMAIL (Governance Canon)

This document is the single-source architecture map for the **Gmail Plumber** subsystem:

- "Gmail Plumber" = `triage` + `newsletter-weekly` (polling, reporting, optional safe writes)
- "Brief products" = deterministic Telegram payloads built from local reports (MB/EOD/Top3)

Evidence anchor (mapping audit bundle):

- `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/gmail-arch-20260214T230718Z/`

## Canonical Definitions

Canonical (SoT local):

- Historical ledger (append-only): `/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports/`
  - `gmail-triage-*.json`
  - `newsletter-weekly-*.json`

Derived (overwrite allowed):

- `/home/rotemgrosman/jarvis-stack/jarvis-data/morning-brief/`
- `/home/rotemgrosman/jarvis-stack/jarvis-data/eod/`
- `/home/rotemgrosman/jarvis-stack/jarvis-data/weekly-top3/`

Derived (newsletter weekly standard; archive + latest):

- Archive root: `/home/rotemgrosman/jarvis-stack/jarvis-data/archive/newsletter-weekly/`
- Latest pointer: `/home/rotemgrosman/jarvis-stack/jarvis-data/newsletter-weekly/latest` (symlink)

## Component Inventory (Flows -> Scripts -> Triggers -> Artifacts)

| Flow | Script(s) | Trigger Authority | Trigger Surface | Canonical Inputs | Outputs |
|---|---|---|---|---|---|
| Daily triage | `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/gmail_triage_poll.py` (`--mode triage`) | systemd | `clawdbot-gmail-triage.timer` | Gmail + `/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/config.json` | Canonical report: `gmail-triage-*.json` under `gmail-triage/reports/` |
| Newsletter master (weekly) | `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/gmail_triage_poll.py` (`--mode newsletter-weekly`) | systemd | `clawdbot-newsletter-master.timer` | Gmail + allowlist + config | Canonical report: `newsletter-weekly-*.json` under `gmail-triage/reports/` |
| Morning brief | `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/morning_brief_probe.py` + `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/brief_validate.py` | Gateway cron | Cron job `morning-brief` | Reads local reports in `gmail-triage/reports/` | Derived: `jarvis-data/morning-brief/{message.txt,signals.json}` |
| End-of-day summary | `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/eod_summary_probe.py` + `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/brief_validate.py` | Gateway cron | Cron job `end-of-day-summary` | Reads local triage reports | Derived: `jarvis-data/eod/{message.txt,signals.json}` |
| Weekly TOP-3 | `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/weekly_top3_probe.py` + `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/brief_validate.py` | Gateway cron | Cron job `weekly-top3` | Reads local triage reports (`new_threads[]`) | Derived: `jarvis-data/weekly-top3/{message.txt,signals.json,report.json}` |
| Newsletter weekly build (derived) | `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/newsletter_weekly_probe.py` | N/A (manual or future wiring) | Must be explicitly wired | Reads `newsletter-weekly-*.json` from canonical ledger | Derived run dir: `telegram_message.txt`, `report.json`, `report.md`, `signals.json`, `evidence.json` |

## Notes On External Surfaces

- Telegram delivery in this stack is performed by:
  - Gateway cron jobs with `payload.deliver=true` (deterministic `cat message.txt` pattern), and
  - The systemd-driven `gmail_triage_poll.py` which calls `clawdbot message send --channel telegram ...` internally.

See `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/docs/governance/canon/CONTRACTS_TELEGRAM.md`.

## What Is Authoritative

- Scheduler authority:
  - systemd (Gmail Plumber polling): `/home/rotemgrosman/.config/systemd/user/clawdbot-gmail-triage.timer`, `/home/rotemgrosman/.config/systemd/user/clawdbot-newsletter-master.timer`
  - Gateway cron (Telegram briefs only): `/home/rotemgrosman/.clawdbot/cron/jobs.json`
- Canonical ledger (SoT local):
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports/`
- Workflow SoT:
  - `/home/rotemgrosman/clawd/workflows`

## What Is Derived

- Brief products (overwrite allowed):
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/morning-brief/`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/eod/`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/weekly-top3/`
- Workflow mirror (generated, read-only):
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/workflows`
- Newsletter weekly derived outputs (archive + latest):
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/archive/newsletter-weekly/`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/newsletter-weekly/latest`

## What Must Stay Disabled

Duplicate-intent cron jobs (must remain disabled forever; Canon Guard MUST fail if enabled):

- `gmail-plumber-daily`
- `newsletter-master-weekly`
- `daily-morning-report`

## Sources

- Canon Guard baseline pointer:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-baseline`
- Canon Guard index pointer:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-index.json`
- systemd units:
  - `/home/rotemgrosman/.config/systemd/user/clawdbot-gmail-triage.timer`
  - `/home/rotemgrosman/.config/systemd/user/clawdbot-newsletter-master.timer`
- Entry points:
  - `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/gmail_triage_poll.py`
  - `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/morning_brief_probe.py`
  - `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/eod_summary_probe.py`
  - `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/weekly_top3_probe.py`
  - `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/newsletter_weekly_probe.py`

## Verification

Run Canon Guard (writes evidence only under `jarvis-data/audit/`):

```bash
orbctl run -m ubuntu -w /home/rotemgrosman/jarvis-stack/jarvis/clawdbot bash -lc '
cd ops/checks
python3 canon_guard_run_all.py
'
```
