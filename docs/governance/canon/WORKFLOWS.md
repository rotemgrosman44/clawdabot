# WORKFLOWS (Governance Canon)

This document defines the Workflow Source of Truth (SoT) and how drift is detected and handled.

## Binding Decision

Workflow SoT is:

- `/home/rotemgrosman/clawd/workflows`

Mirror-only (non-SoT) directory:

- `/home/rotemgrosman/jarvis-stack/jarvis-data/workflows`

## Governance Invariant

- Operators and jobs must treat SoT as canonical.
- Mirror is **generated** from SoT and is **read-only** (no manual edits).
- Mirror may exist for compatibility, but must not silently drift without a report.

## Mirror Metadata (Required When Mirror Exists)

If the mirror directory exists, it must include generation metadata:

- `/home/rotemgrosman/jarvis-stack/jarvis-data/workflows/mirror_meta.json`

The metadata must include:

- `generated_from.sot_dir` (SoT path)
- `generated_at` (UTC ISO timestamp)
- `files` (sha256 list, count)

This metadata is used to distinguish "generated but stale" from "unknown drift".

## Enforcement (Read-only)

Canon Guard must:

- Hash all `*.yaml` under the SoT directory.
- If the mirror directory exists, hash it too.
- Emit a drift report listing:
  - files missing on either side
  - same filename with different sha256

No files are modified by the detector.

## Migration / Archival Plan (Phase C)

Until Phase C is executed:

- SoT remains `/home/rotemgrosman/clawd/workflows`.
- Mirror drift is tolerated only as a reported non-compliance (WARN) when generation metadata is missing.

## What Is Authoritative

- Workflow Source of Truth (SoT):
  - `/home/rotemgrosman/clawd/workflows`

## What Is Derived

- Workflow mirror (generated, read-only):
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/workflows`
- Mirror generation metadata (required when mirror exists):
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/workflows/mirror_meta.json`

## What Must Stay Disabled

- Manual edits to the mirror are forbidden (treat as operationally disabled).
- Duplicate-intent cron jobs (must remain disabled forever; Canon Guard MUST fail if enabled):
  - `gmail-plumber-daily`
  - `newsletter-master-weekly`
  - `daily-morning-report`

## Sources

- Canon Guard baseline pointer:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-baseline`
- Workflow SoT:
  - `/home/rotemgrosman/clawd/workflows`
- Workflow mirror:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/workflows`

## Verification

Run Canon Guard and inspect the workflows SoT report:

```bash
orbctl run -m ubuntu -w /home/rotemgrosman/jarvis-stack/jarvis/clawdbot bash -lc '
cd ops/checks
python3 canon_guard_run_all.py
D=$(readlink -f /home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-latest)
sed -n \"1,220p\" \"$D/workflows_sot_report.md\"
'
```
