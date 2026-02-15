# Canon Baseline (Stable)

This baseline is enforced by **Canon Guard** and pinned by stable pointers in `jarvis-data/audit/`.

## What Is Authoritative

- Scheduler authority:
  - systemd (polling): `/home/rotemgrosman/.config/systemd/user/clawdbot-gmail-triage.timer`, `/home/rotemgrosman/.config/systemd/user/clawdbot-newsletter-master.timer`
  - Gateway cron (briefs only): `/home/rotemgrosman/.clawdbot/cron/jobs.json`
- Safety (SAFE_READONLY): `/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/config.json`
- Workflow SoT: `/home/rotemgrosman/clawd/workflows`
- Newsletter weekly canon: archive + latest:
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/archive/newsletter-weekly/`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/newsletter-weekly/latest`

## What Is Derived

- Brief products (overwrite allowed):
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/morning-brief/`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/eod/`
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/weekly-top3/`
- Workflow mirror (generated, read-only):
  - `/home/rotemgrosman/jarvis-stack/jarvis-data/workflows`

## What Must Stay Disabled

Duplicate-intent cron jobs (must remain disabled forever):

- `gmail-plumber-daily`
- `newsletter-master-weekly`
- `daily-morning-report`

## Sources (Stable Pointers)

- Latest Canon Guard run: `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-latest`
- Baseline (last PASS): `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-baseline`
- Index: `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-index.json`

## Verification

```bash
orbctl run -m ubuntu -w /home/rotemgrosman/jarvis-stack/jarvis/clawdbot bash -lc '
cd ops/checks
python3 canon_guard_run_all.py
D=$(readlink -f /home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-latest)
echo "LATEST=$D"
jq -r ".overall_status" "$D/canon_guard_report.json"
jq -r ".parts" "$D/canon_guard_report.json"
'
```

## Runtime Pin Policy (Binding)

No systemd-executed script may differ from `git HEAD`. If drift is detected:

1. Quarantine evidence (must write a new bundle under `jarvis-data/audit/quarantine-<timestamp>/`):
   - `git_status.txt`
   - `git_diff_stat.txt`
   - `full_worktree.patch`
   - file-specific patch(es) for the drifted runtime entrypoint(s)
2. Resolve drift deterministically:
   - Either revert the drifted file(s) to `HEAD`, or
   - Canonize changes via a reviewed commit on a canon branch (then the file matches `HEAD`).
3. Stop and re-run Canon Guard. Do not restart schedulers until hygiene is clean.

## Closure-Grade PASS (Definition)

Closure is only achieved when all of the following are true:

- Canon Guard overall status is `PASS` (see `canon-guard-latest/canon_guard_report.json`), and
- Hygiene is clean: `dirty_referenced_paths == []` in `canon-guard-latest/canon_hygiene_report.json`.
