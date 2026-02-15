# CONTRACTS_TELEGRAM (Governance Canon)

This document specifies the deterministic Telegram payload contract used by Gateway Cron Jobs.

## Deterministic Pattern (Binding)

For brief products (MB/EOD/Top3), the cron job payload MUST implement:

1. **Probe**: run a local probe script that writes artifacts under `jarvis-data/<product>/`.
2. **Validate**: run `brief_validate.py` with product-specific constraints.
3. **Cat**: `cat /home/rotemgrosman/jarvis-stack/jarvis-data/<product>/message.txt`
4. **Deliver**: The agent response MUST be exactly the output of step 3 (verbatim, no extra text).

Evidence:

- Cron payloads are stored in `/home/rotemgrosman/.clawdbot/cron/jobs.json` and visible via `clawdbot cron list --all --json`.

## Product Contracts (Current)

Morning Brief (`morning-brief`)

- Probe: `/usr/bin/python3 /home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/morning_brief_probe.py`
- Validate: `brief_validate.py` requires:
  - `--product-token "MORNING_BRIEF"`
  - `--lines-exact 8`
  - `--require-signal-prefix "SIGNAL MB|"`
  - `--signal-max-len 120`
  - `--message .../jarvis-data/morning-brief/message.txt`
  - `--signals .../jarvis-data/morning-brief/signals.json`
- Deliver: `deliver=true`, `channel=telegram`, `to=<chat_id>`

End-of-Day Summary (`end-of-day-summary`)

- Probe: `/usr/bin/python3 /home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/eod_summary_probe.py`
- Validate requires:
  - `--product-token "EOD_SUMMARY"`
  - `--lines-min 12 --lines-max 15`
  - `--require-signal-prefix "SIGNAL EOD|"`
  - `--signal-max-len 120`
  - `--message .../jarvis-data/eod/message.txt`
  - `--signals .../jarvis-data/eod/signals.json`

Weekly TOP-3 (`weekly-top3`)

- Probe: `/usr/bin/python3 /home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/weekly_top3_probe.py`
- Validate requires:
  - `--product-token "WEEKLY_TOP3"`
  - `--lines-exact 6`
  - `--require-signal-prefix "SIGNAL W|"`
  - `--signal-max-len 120`
  - `--message .../jarvis-data/weekly-top3/message.txt`
  - `--signals .../jarvis-data/weekly-top3/signals.json`

## SIGNAL Token Rules (Binding)

Signals are written to `signals.json` with a `signal_token` field and must:

- Begin with the product prefix: `SIGNAL MB|`, `SIGNAL EOD|`, `SIGNAL W|`
- Remain short (max 120 characters per validator constraints)

## Non-Goals

- This contract does not define how `gmail_triage_poll.py` sends Telegram (systemd path).
- This contract does not authorize Drive publishing.

## What Is Authoritative

- Gateway cron (brief products) is authoritative for deterministic Telegram delivery:
  - Job store: `/home/rotemgrosman/.clawdbot/cron/jobs.json`
  - Allowlist: `morning-brief`, `end-of-day-summary`, `weekly-top3`
- Validator and product contract shape:
  - `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/brief_validate.py`

## What Is Derived

- Brief message artifacts written locally and then delivered by the Gateway cron runner:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/morning-brief/message.txt`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/eod/message.txt`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/weekly-top3/message.txt`

## What Must Stay Disabled

Duplicate-intent cron jobs (must remain disabled forever; Canon Guard MUST fail if enabled):

- `gmail-plumber-daily`
- `newsletter-master-weekly`
- `daily-morning-report`

## Sources

- Canon Guard baseline pointer:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-baseline`
- Canon Guard scheduler report (within baseline bundle):
  - `scheduler_guard_report.md`
- Canon Guard artifacts contract report (within baseline bundle):
  - `artifacts_contract_report.md`

## Verification

Run Canon Guard and inspect the scheduler and artifacts reports:

```bash
orbctl run -m ubuntu -w /home/rotemgrosman/jarvis-stack/jarvis/clawdbot bash -lc '
cd ops/checks
python3 canon_guard_run_all.py
D=$(readlink -f /home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-latest)
sed -n \"1,200p\" \"$D/scheduler_guard_report.md\"
sed -n \"1,200p\" \"$D/artifacts_contract_report.md\"
'
```
