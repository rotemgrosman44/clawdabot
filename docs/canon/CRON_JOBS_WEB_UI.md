# Cron Jobs Via Web UI (Authoritative Scheduler)

In this deployment, the **Cron Jobs page** (Gateway scheduler) is authoritative.

- Job store: `/home/rotemgrosman/.clawdbot/cron/jobs.json`
- CLI: `clawdbot cron ...` (talks to the Gateway)
- The **Config → Cron** toggle is not authoritative here (canonical config has no `.cron` key).

## Where To Manage Jobs

Use:

- Web UI → **Cron Jobs**
- CLI: `clawdbot cron status|list|add|edit|rm|run|runs`

Do not try to force `.cron` into `/home/rotemgrosman/jarvis-stack/jarvis-data/clawdbot.json` just for UI parity.

## Job Model (What The UI Writes)

Each job record has:

- `name`, `description`, `enabled`
- `schedule`: `kind=every|cron|at`
- `sessionTarget`: `main|isolated`
- `payload`: what the job injects
- `wakeMode`: `next-heartbeat|now`

Examples from the current store show `sessionTarget=main` + `payload.kind=systemEvent`.

## Scheduling Fields

1. Interval schedule
   - UI “Every …”
   - Store: `schedule.kind="every"`, `schedule.everyMs=<ms>`
   - CLI equivalent: `clawdbot cron add --every 30m ...`

2. Cron expression schedule
   - UI “Cron …”
   - Store: `schedule.kind="cron"`, `schedule.expr="<5-field>"`, `schedule.tz="Asia/Jerusalem"`
   - CLI equivalent: `clawdbot cron add --cron "0 9-20/2 * * *" --tz "Asia/Jerusalem" ...`

3. One-shot schedule
   - UI “At …”
   - Store: `schedule.kind="at"`, `schedule.atMs=<epoch-ms>`
   - CLI equivalent: `clawdbot cron add --at "2026-02-10T09:00:00+02:00" ...`

## Payload Conventions

There are two supported execution styles:

1. **Main session job (recommended default in this environment)**
   - Store: `sessionTarget="main"`
   - Store: `payload.kind="systemEvent"`, `payload.text="<system instruction>"`
   - UI fields usually appear as:
     - Payload: “System event”
     - System text: “...”
   - CLI equivalent: `clawdbot cron add --session main --system-event "<text>" ...`

2. **Isolated job (recommended for noisy/background jobs)**
   - Store: `sessionTarget="isolated"`
   - Store: `payload.kind="agentTurn"`, `payload.message="<prompt>"`
   - Optional delivery:
     - `payload.deliver=true`, `payload.channel="telegram"`, `payload.to="<chat_id>"`
   - CLI equivalent:
     - `clawdbot cron add --session isolated --message "<text>" --deliver --channel telegram --to <chat_id> ...`

## Agent And Session Recommendations

- If you want the job to run “as the main agent with full shared context”, use:
  - `sessionTarget=main`
  - `payload.kind=systemEvent`
- If you want a job to be “background-only” and avoid polluting main context, use:
  - `sessionTarget=isolated`
  - `payload.kind=agentTurn`
  - Set delivery explicitly (`telegram` + `to`) so output doesn’t depend on “last route”.
- `agentId`:
  - Use it only if you have multiple agents configured and want deterministic separation (e.g. `newsletter-master` vs `email-triage`).
  - Otherwise leave unset and rely on the default agent.

## Verify The UI Change Took Effect

After adding/editing a job in Web UI:

1. Confirm the job exists via CLI:

```bash
export PATH=/home/rotemgrosman/.npm-global/bin:$PATH
clawdbot cron list --json | jq -r '.jobs[] | {id,name,enabled,sessionTarget,schedule:.schedule.kind}'
```

2. Confirm it’s persisted in the store:

```bash
jq -r '{version, jobs_count:(.jobs|length)}' /home/rotemgrosman/.clawdbot/cron/jobs.json
```

3. Test-run it (debug):

```bash
export PATH=/home/rotemgrosman/.npm-global/bin:$PATH
clawdbot cron run <jobId> --force
clawdbot cron runs --id <jobId> --limit 5
```

## Reference

Full cron scheduler docs:

`/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/docs/automation/cron-jobs.md`

