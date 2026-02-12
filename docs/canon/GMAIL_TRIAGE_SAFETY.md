# Gmail Polling Triage Safety Policy (Canon)

## Scope

This phase is polling-only triage:

- Gmail: search and summarize only.
- Delivery: Telegram message via `clawdbot message send`.
- No webhooks, no Pub/Sub push.

## Hard Safety Guarantees

- No outbound email sending is used or enabled in the triage runner.
- No destructive Gmail actions are executed by the runner:
  - No delete
  - No trash
  - No modify
  - No label changes
- Hooks remain disabled in canonical config (`.hooks.enabled=false`).

## Plan Mode Only

The triage message includes a `PLAN (no execution)` section.

- It may list proposed actions derived from a newsletter allowlist.
- Proposed actions are capped at 20 non-spam proposals per run.
- Proposals are recorded in the per-run JSON report.

No plan actions are executed in this phase.

## Secrets Handling

- OAuth and keyring secrets live outside the repo.
- The systemd unit uses `EnvironmentFile=` for gog keyring env.
- Never print `keyring.env`, tokens, refresh tokens, client secrets, or provider API keys in terminal output.

## Future Enablement (Not In This Phase)

If and only if explicitly approved:

- Allow limited destructive actions behind explicit config gates.
- Add a human approval workflow for any non-spam deletes or modifications.

