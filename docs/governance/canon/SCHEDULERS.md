# SCHEDULERS (Governance Canon)

This document defines the **authority matrix** for schedulers and the **forbidden states** that Canon Guard must detect.

Evidence anchor:

- `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/gmail-arch-20260214T230718Z/`

## Authority Matrix (Binding)

| Flow | Authoritative Scheduler | Non-authoritative Scheduler |
|---|---|---|
| Gmail polling: `gmail_triage_poll.py --mode triage` | systemd user timer | Gateway cron (must not mirror) |
| Gmail polling: `gmail_triage_poll.py --mode newsletter-weekly` | systemd user timer | Gateway cron (must not mirror) |
| Telegram briefs (deterministic: probe -> validate -> cat -> deliver) | Gateway cron (Gateway scheduler) | systemd (must not run these) |

## systemd Units (Authoritative)

Canonical unit paths:

- `/home/rotemgrosman/.config/systemd/user/clawdbot-gmail-triage.timer`
- `/home/rotemgrosman/.config/systemd/user/clawdbot-gmail-triage.service`
- `/home/rotemgrosman/.config/systemd/user/clawdbot-newsletter-master.timer`
- `/home/rotemgrosman/.config/systemd/user/clawdbot-newsletter-master.service`

## Gateway Cron Jobs (Authoritative For Briefs)

Canonical store:

- `/home/rotemgrosman/.clawdbot/cron/jobs.json`

Allowed Telegram-delivery cron jobs (current canon allowlist):

- `morning-brief`
- `end-of-day-summary`
- `weekly-top3`

## Duplicated Intent Cron Jobs (Must Remain Disabled Forever)

These cron jobs mirror systemd polling intents and must remain disabled unless governance is explicitly revised:

- `gmail-plumber-daily`
- `newsletter-master-weekly`
- `daily-morning-report`

Rationale: enabling these creates dual scheduler authority for the same intent and introduces drift/double execution.

## Forbidden States (Canon Guard MUST fail fast)

1. systemd timers missing or not enabled:
   - `clawdbot-gmail-triage.timer`
   - `clawdbot-newsletter-master.timer`

2. Duplicated intent cron job is enabled:
   - `gmail-plumber-daily`
   - `newsletter-master-weekly`

3. Any cron job delivers to Telegram that is not on the allowlist:
   - allowlist: `morning-brief`, `end-of-day-summary`, `weekly-top3`

4. Any brief job deviates from deterministic contract:
   - must run probe script
   - must validate contract
   - must return exactly `cat .../message.txt` output (no extra text)

## What Is Authoritative

- systemd (Gmail Plumber polling):
  - `/home/rotemgrosman/.config/systemd/user/clawdbot-gmail-triage.timer`
  - `/home/rotemgrosman/.config/systemd/user/clawdbot-newsletter-master.timer`
- Gateway cron (brief products only):
  - `/home/rotemgrosman/.clawdbot/cron/jobs.json`

## What Is Derived

- Canon Guard scheduler evidence bundles:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-*/scheduler_guard_report.*`

## What Must Stay Disabled

Duplicate-intent cron jobs (must remain disabled forever; Canon Guard MUST fail if enabled):

- `gmail-plumber-daily`
- `newsletter-master-weekly`
- `daily-morning-report`

## Sources

- Canon Guard baseline pointer:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-baseline`
- systemd user units:
  - `/home/rotemgrosman/.config/systemd/user/clawdbot-gmail-triage.timer`
  - `/home/rotemgrosman/.config/systemd/user/clawdbot-newsletter-master.timer`
- Gateway cron job store:
  - `/home/rotemgrosman/.clawdbot/cron/jobs.json`

## Verification

Run Canon Guard and inspect the scheduler report:

```bash
orbctl run -m ubuntu -w /home/rotemgrosman/jarvis-stack/jarvis/clawdbot bash -lc '
cd ops/checks
python3 canon_guard_run_all.py
D=$(readlink -f /home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-latest)
sed -n \"1,240p\" \"$D/scheduler_guard_report.md\"
'
```
