# Gmail Polling Triage Troubleshooting

## Quick Health (No Secrets)

Gateway should be healthy in Ubuntu:

```bash
systemctl --user is-active clawdbot-gateway.service
curl -fsS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:18789/ || echo CURL_FAIL
```

Timer and last run:

```bash
systemctl --user status clawdbot-gmail-triage.timer -l --no-pager | sed -n "1,80p"
systemctl --user status clawdbot-gmail-triage.service -l --no-pager | sed -n "1,120p"
```

Logs:

```bash
journalctl --user -u clawdbot-gmail-triage.service --since today --no-pager | tail -n 120
```

## No Telegram Message Arrived

Check:

```bash
systemctl --user list-timers --all | rg gmail-triage
```

Then force-run:

```bash
systemctl --user start clawdbot-gmail-triage.service
```

If the unit fails, read the last JSON status line in the service logs:

```bash
journalctl --user -u clawdbot-gmail-triage.service -n 60 --no-pager
```

## Gmail Auth Problems

The runner expects gog keyring env to be loaded by systemd via `EnvironmentFile=...`.

To check gog auth *without printing secrets*, run:

```bash
set -a
. /home/rotemgrosman/.config/gogcli/keyring.env
set +a
gog auth list --plain
```

If auth fails, re-run the gog auth flow (see the operational runbook for gog).

## Dedupe / Duplicate Sends

State and reports:

`/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/state.json`

`/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports/`

Important semantics:

- State is committed only after successful Telegram send.
- If Telegram send fails, the run exits non-zero and state is not advanced.

## Disable Temporarily

```bash
systemctl --user disable --now clawdbot-gmail-triage.timer
```

