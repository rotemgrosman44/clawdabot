# Gmail Polling Triage Scheduler (Systemd User Timer)

This stack runs Gmail polling triage via a systemd *user* timer and service.

## Units

Units live under:

`/home/rotemgrosman/.config/systemd/user/`

Relevant files:

`/home/rotemgrosman/.config/systemd/user/clawdbot-gmail-triage.timer`

`/home/rotemgrosman/.config/systemd/user/clawdbot-gmail-triage.service`

## Schedule

The authoritative schedule is whatever is defined in the systemd timer file.

Observed in this deployment (see `systemctl --user cat clawdbot-gmail-triage.timer`):

- `OnCalendar=Sun,Mon,Tue,Wed,Thu *-*-* 14:00:00`

Verify the timer definition:

```bash
systemctl --user cat clawdbot-gmail-triage.timer
```

Verify system timezone:

```bash
timedatectl show -p Timezone --value
```

Verify next trigger:

```bash
systemctl --user list-timers --all | rg gmail-triage
```

## Status And Logs

Timer status:

```bash
systemctl --user status clawdbot-gmail-triage.timer -l --no-pager
```

Last run status:

```bash
systemctl --user status clawdbot-gmail-triage.service -l --no-pager
```

Logs (today):

```bash
journalctl --user -u clawdbot-gmail-triage.service --since today --no-pager
```

## Force Run

Run a one-shot triage immediately:

```bash
systemctl --user start clawdbot-gmail-triage.service
```

## Disable Or Pause

Disable and stop future scheduled runs:

```bash
systemctl --user disable --now clawdbot-gmail-triage.timer
```

Re-enable:

```bash
systemctl --user enable --now clawdbot-gmail-triage.timer
```

## Artifacts (Autonomy Proof)

Runner state and audit files:

`/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/state.json`

`/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports/`

Quick check (no email subjects):

```bash
ls -t /home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports/gmail-triage-*.json | head -n 3
```
