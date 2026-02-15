# SUBAGENTS (Governance Canon)

This document defines the canonical naming registry for email-related subagents and records known drift.

## Definitions

- Runtime subagent state (authoritative state store):
  - `/home/rotemgrosman/.clawdbot/subagents/<name>/`
- Workspace subagent definitions (editable workspace):
  - `/home/rotemgrosman/clawd/subagents/<name>/`

## Binding Registry Rule

Canonical names are the runtime subagent directory names under:

- `/home/rotemgrosman/.clawdbot/subagents/`

Workspace names are treated as aliases until Phase D converges naming.

## Registry Table (Observed)

Evidence anchor:

- `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/gmail-arch-20260214T230718Z/subagents_runtime_dirs.txt`
- `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/gmail-arch-20260214T230718Z/subagents_workspace_dirs.txt`

| Canonical Name (runtime) | Runtime Path | Workspace Alias (if any) | Workspace Path |
|---|---|---|---|
| `gmail-plumber` | `/home/rotemgrosman/.clawdbot/subagents/gmail-plumber/` | `email-triage` | `/home/rotemgrosman/clawd/subagents/email-triage/` |
| `newsletter-master` | `/home/rotemgrosman/.clawdbot/subagents/newsletter-master/` | `newsletter-master` | `/home/rotemgrosman/clawd/subagents/newsletter-master/` |
| `invoices-gmail-agent` | `/home/rotemgrosman/.clawdbot/subagents/invoices-gmail-agent/` | `invoice-manager` | `/home/rotemgrosman/clawd/subagents/invoice-manager/` |
| `il-index-growth-manager` | `/home/rotemgrosman/.clawdbot/subagents/il-index-growth-manager/` | `ai-news-digest` | `/home/rotemgrosman/clawd/subagents/ai-news-digest/` |

## Phase D Migration Plan (No Execution Here)

1. Produce a stable mapping file (registry) under governance docs.
2. Decide convergence direction:
   - rename workspace dirs to canonical runtime names, or
   - rename runtime dirs to workspace names (higher risk; impacts state paths)
3. Execute rename/alias changes one at a time with an audit bundle and rollback.

## What Is Authoritative

- Runtime canonical subagent names (SoT for operations):
  - `/home/rotemgrosman/.clawdbot/subagents/`
- Canon registry for operators:
  - This document: `/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/docs/governance/canon/SUBAGENTS.md`

## What Is Derived

- Workspace aliases and development-time directory names (non-authoritative):
  - `/home/rotemgrosman/clawd/subagents/`

## What Must Stay Disabled

Duplicate-intent cron jobs (must remain disabled forever; Canon Guard MUST fail if enabled):

- `gmail-plumber-daily`
- `newsletter-master-weekly`
- `daily-morning-report`

## Sources

- Mapping evidence bundle:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/gmail-arch-20260214T230718Z/`
- Canon Guard baseline pointer:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-baseline`

## Verification

Run Canon Guard (to ensure no scheduler drift) and then re-check the mapping evidence bundle remains present:

```bash
orbctl run -m ubuntu -w /home/rotemgrosman/jarvis-stack/jarvis/clawdbot bash -lc '
cd ops/checks
python3 canon_guard_run_all.py
ls -la /home/rotemgrosman/jarvis-stack/jarvis-data/audit/gmail-arch-20260214T230718Z | sed -n \"1,40p\"
'
```
