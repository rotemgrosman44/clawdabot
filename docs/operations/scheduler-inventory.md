# Scheduler Inventory (Gateway)

## Snapshot
- Reported by Web UI: 27 cron jobs
- Some enabled, some isolated, some error

## Authority boundaries (must not mix)
- Gateway scheduler jobs are internal to OpenClaw Gateway (Web UI)
- They are NOT Linux/systemd timers
- They are NOT affected by jarvis-snapshot.timer
- If probing /api/cron-jobs returns SPA HTML, treat it as routing/auth boundary (not "missing API")

## Known separate schedulers in this stack
- systemd timers: background agents (e.g., gmail triage/newsletter)
- Cron (Clawdbot cron): conversational agent turns (morning brief, end-of-day)

## Evidence
- Screenshot bundle: <path to screenshots>
- API probe note: <redacted snippet>

## Audit note
- UI reports 27 jobs, but only 24 jobs were visible during this capture (API rate limit and/or UI sync suspected). Registry was populated with the 24 captured entries. No consolidation actions were taken.
