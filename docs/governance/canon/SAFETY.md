# SAFETY (Governance Canon)

This document is the canonical safety standard for Gmail Plumber operations. It must not contradict runtime gates.

## Scope

This governs:

- `gmail_triage_poll.py --mode triage`
- `gmail_triage_poll.py --mode newsletter-weekly`
- Derived brief products (MB/EOD/Top3) that read local reports and deliver deterministic Telegram payloads.

## Runtime Safety Gates (Source of Truth)

Runtime gates are defined in:

- `/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/config.json`

Key fields (expected to exist):

- `.write.enabled`
- `.write.policy.allowedActions` (e.g. `label`, `archive`, `trash`)
- `.safety.allowPermanentDelete` (must remain `false`)

## Binding Default: SAFE_READONLY

Canonical default is **SAFE_READONLY**:

- `.write.enabled=false`
- No label changes, no archive, no trash, no modifications.

Write capabilities may exist in config as an allowlist for future use, but are inert unless `.write.enabled=true`.

## Governance Rule: No Silent Write Expansion (Binding)

If Gmail write capability exists, it must be explicitly documented here and reflected in config.

- Any change that expands write scope is a governance change and requires explicit operator approval.
- Canon Guard must detect contradictions between this document and runtime config.

## Write Feature Flag (Binding)

If `.write.enabled=true`, config must include an explicit operator acknowledgement flag (feature flag).

Canon Guard must FAIL if:

- `.write.enabled=true` and the feature flag is missing or unexpected.

## Allowed Write Classes (Config-Anchored)

Allowed writes are determined solely by `jarvis-data/gmail-triage/config.json`. Canon Guard reports the live values.

Hard prohibition:

- Permanent delete must remain disabled (`allowPermanentDelete=false`).

## Kill Switch Procedure (Emergency)

Objective: disable Gmail writes quickly and deterministically.

This procedure requires explicit operator approval before execution.

1. Edit `/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/config.json`:
   - Set `.write.enabled=false`
   - Optionally set `.write.trash.enabled=false` and `.write.labels.enabled=false`
2. Restart the authoritative scheduler service (systemd user service):
   - `systemctl --user restart clawdbot-gmail-triage.service`
   - `systemctl --user restart clawdbot-newsletter-master.service`
3. Verify via latest reports:
   - `writeStats` and `writeAudit` reflect disabled writes

## Telegram Safety (Brief Products)

Cron-based brief products deliver Telegram deterministically by returning the exact contents of a local `message.txt`.

This implies:

- No dynamic network calls are required for brief generation.
- The only outbound side effect is Telegram delivery performed by the Gateway when `deliver=true` is set for the cron job.

See `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/docs/governance/canon/CONTRACTS_TELEGRAM.md`.

## What Is Authoritative

- Live safety gates (SoT local runtime config):
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/config.json`
- Canon Guard enforcement:
  - `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/ops/checks/canon_guard_artifacts.py`

## What Is Derived

- Audit evidence bundles produced by Canon Guard:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-*/`

## What Must Stay Disabled

- Default posture is SAFE_READONLY (must remain true unless an explicit write feature flag is used and documented):
  - `.write.enabled=false`
  - `.write.trash.enabled=false`
  - `.write.labels.enabled=false`
  - `.safety.allowPermanentDelete=false`
- Duplicate-intent cron jobs (must remain disabled forever; Canon Guard MUST fail if enabled):
  - `gmail-plumber-daily`
  - `newsletter-master-weekly`
  - `daily-morning-report`

## Sources

- Canon Guard baseline pointer:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-baseline`
- Live safety config:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/config.json`

## Verification

Run Canon Guard and confirm the safety section passes:

```bash
orbctl run -m ubuntu -w /home/rotemgrosman/jarvis-stack/jarvis/clawdbot bash -lc '
cd ops/checks
python3 canon_guard_run_all.py
D=$(readlink -f /home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-latest)
sed -n \"1,260p\" \"$D/artifacts_contract_report.md\"
'
```
