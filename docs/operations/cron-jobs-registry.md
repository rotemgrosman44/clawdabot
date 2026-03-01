# Cron Jobs Registry (Gateway Scheduler)

## Source of truth
- Captured from OpenClaw Gateway Web UI (Agent: main)
- Workspace: /home/rotemgrosman/clawd
- Primary Model: google/gemini-2.5-flash
- Scheduler: Enabled (Yes)
- UI reported total jobs: 27
- Captured jobs in this registry: 24
- Capture note: UI displayed "API rate limit reached. Please try again later." During this capture, only 24 jobs were visible. No scheduler changes were executed.

## Schema (per job)
- name
- schedule
- state: enabled | disabled AND isolated/main AND ok/error
- target agent (if stated)
- description (functional)
- inputs/outputs/artifact paths (only if explicitly present)
- evidence (capture source)

---

## Jobs (Captured 24)

### 001) seo-sentinel-daily-0200-intake
- schedule: Cron 0 2 * * * (Asia/Jerusalem)
- state: enabled | isolated | error
- target agent: main
- description: Daily 02:00 email intake + filtering for SEO/newsletter pipeline. Stops intake at T-24 before weekly deadline.
- evidence: UI dump 2026-03-01

### 002) gmail-plumber-daily
- schedule: Cron 0 14 * * 0,1,2,3,4 (Asia/Jerusalem)
- state: enabled | isolated | ok
- target agent: main
- description: Gmail Plumber daily run (Sun-Thu 14:00). Deterministic triage. Telegram only high-signal. Maintain audit files.
- evidence: UI dump 2026-03-01

### 003) seo-sentinel-iteration-window-thu
- schedule: Cron 0 14,20 * * 4 (Asia/Jerusalem)
- state: enabled | isolated | ok
- target agent: main
- description: T-24 Thursday iteration mode. Focus only on quality and formatting. No fresh intake. Canonical weekly docs only.
- evidence: UI dump 2026-03-01

### 004) seo-sentinel-iteration-window-fri
- schedule: Cron 0 2,8 * * 5 (Asia/Jerusalem)
- state: enabled | isolated | error
- target agent: main
- description: Final Friday iteration pass before weekly delivery. Refine existing weekly docs only. Return readiness status.
- evidence: UI dump 2026-03-01

### 005) seo-sentinel-weekly-publish
- schedule: Cron 0 14 * * 5 (Asia/Jerusalem)
- state: enabled | isolated | error
- target agent: main
- description: Finalize and publish weekly SEO deliverable. Title must be "דו״ח שבועי - SEO Sentinel". Canonical docs only.
- evidence: UI dump 2026-03-01

### 006) qmd-weekly-health-report
- schedule: Cron 30 11 * * 0 (Asia/Jerusalem)
- state: enabled | isolated | ok
- target agent: main
- description: Exec read-only. Run qmd status and qmd searches. Send concise Hebrew PASS/FAIL and one remediation step if FAIL.
- evidence: UI dump 2026-03-01

### 007) twitter-loop-report-t5m
- schedule: At 2/27/2026, 3:59:23 AM
- state: disabled | isolated | error
- target agent: main
- description: Read twitter closed-loop json/log and send concise Hebrew status (max 4 lines).
- inputs: /home/rotemgrosman/clawd/state/twitter-closed-loop.json, /home/rotemgrosman/clawd/logs/twitter-closed-loop.log
- evidence: UI dump 2026-03-01

### 008) twitter-loop-report-t10m
- schedule: At 2/27/2026, 4:04:24 AM
- state: disabled | isolated | error
- target agent: main
- description: Same intent as t5m.
- evidence: UI dump 2026-03-01

### 009) twitter-loop-report-t15m
- schedule: At 2/27/2026, 4:09:24 AM
- state: disabled | isolated | error
- target agent: main
- description: Same intent as t5m.
- evidence: UI dump 2026-03-01

### 010) twitter-loop-report-t20m
- schedule: At 2/27/2026, 4:14:25 AM
- state: disabled | isolated | error
- target agent: main
- description: Same intent as t5m.
- evidence: UI dump 2026-03-01

### 011) twitter-loop-report-t25m
- schedule: At 2/27/2026, 4:19:26 AM
- state: disabled | isolated | error
- target agent: main
- description: Same intent as t5m.
- evidence: UI dump 2026-03-01

### 012) twitter-loop-report-t30m
- schedule: At 2/27/2026, 4:24:26 AM
- state: disabled | isolated | error
- target agent: main
- description: Same intent as t5m.
- evidence: UI dump 2026-03-01

### 013) deliverables-pulse-morning
- schedule: Cron 35 9 * * * (Asia/Jerusalem)
- state: disabled | isolated | error
- target agent: main
- description: Telegram deliverables update (morning). Reads drive-links.json and includes exact Google Drive links. 6-10 lines.
- inputs: /home/rotemgrosman/clawd/ops/deliverables/drive-links.json
- evidence: UI dump 2026-03-01

### 014) deliverables-pulse-evening
- schedule: Cron 10 20 * * * (Asia/Jerusalem)
- state: disabled | isolated | ok
- target agent: main
- description: Telegram deliverables update (evening). Same schema as morning.
- inputs: /home/rotemgrosman/clawd/ops/deliverables/drive-links.json
- evidence: UI dump 2026-03-01

### 015) memory-consolidation-dryrun-nightly
- schedule: Cron 10 2 * * * (Asia/Jerusalem)
- state: disabled | isolated | error
- target agent: main
- description: Read-only. Review memory paths and propose what to promote to MEMORY.md, what to deprecate, missing paths. 8-12 lines.
- inputs: /home/rotemgrosman/clawd/memory/, /home/rotemgrosman/second-brain/, /home/rotemgrosman/jarvis-stack/jarvis/workflows/reports/
- evidence: UI dump 2026-03-01

### 016) newsletter-master-weekly
- schedule: Cron 0 14 * * 5 (Asia/Jerusalem)
- state: disabled | main | ok
- target agent: System
- description: Newsletter Master weekly. Build digest from allowlisted sources then apply safe cleanup policy and update audit.
- evidence: UI dump 2026-03-01

### 017) qmd-nightly-index-refresh
- schedule: Cron 25 2 * * * (Asia/Jerusalem)
- state: disabled | isolated | error
- target agent: main
- description: Exec read-only. Run qmd update then qmd status. Report indexed totals and whether errors detected.
- evidence: UI dump 2026-03-01

### 018) twitter-operator-rlhf-loop
- schedule: Cron 0 9-21/2 * * * (Asia/Jerusalem)
- state: disabled | main | ok
- target agent: System
- description: Reminder loop check. Verify published tweets, enforce daily target, collect metrics, send concise status.
- evidence: UI dump 2026-03-01

### 019) morning-brief
- schedule: Cron 0 7 * * * (Asia/Jerusalem)
- state: disabled | isolated | error
- target agent: main
- description: Runs morning_brief_probe.py then brief_validate then cats message.txt. Response must be exactly cat output. Sends Telegram.
- evidence: UI dump 2026-03-01

### 020) skills-install-brief
- schedule: Cron 0 7 * * * (Asia/Jerusalem)
- state: disabled | main | ok
- target agent: System
- description: Reminder. Confirm Universal Skills Manager installed on Jarvis, Claude Code, Codex. Plan canonical sync documents.
- evidence: UI dump 2026-03-01

### 021) twitter-operator-v2
- schedule: Cron 0 9-21/2 * * * (Asia/Jerusalem)
- state: disabled | isolated | error
- target agent: main
- description: Autonomous Twitter operator. Requires relay attached. Up to 20 actions/run. Report every 3 publishes. Stop on relay drop.
- evidence: UI dump 2026-03-01

### 022) evening-brief
- schedule: Cron 0 20 * * * (Asia/Jerusalem)
- state: disabled | isolated | error
- target agent: main
- description: Runs eod_summary_probe.py then brief_validate then cats eod message.txt. Response must be exactly cat output. Sends Telegram.
- evidence: UI dump 2026-03-01

### 023) research-spec-deadline
- schedule: At 2/20/2026, 7:00:00 PM
- state: disabled | main | ok
- target agent: System
- description: Reminder. Deliver the 48h research specification report.
- evidence: UI dump 2026-03-01

### 024) zoom-recordings-reminder
- schedule: Cron 0 9 16 2 * (Asia/Jerusalem)
- state: disabled | isolated | ok
- target agent: main
- description: Reminder: connect Zoom recordings & transcripts folder to Clawdbot. Exact message only.
- evidence: UI dump 2026-03-01

---

## Missing jobs (not visible during capture)
- Count missing: 3
- Cause: UI reported 27 jobs, but only 24 were visible while rate-limited.
- Action required later: re-capture the list when UI rate-limit clears, or export scheduler store if available.
- This section is informational only. It does not require manual entry at this time.

---

## Dependency Map & Collision Analysis
NOTE: Deferred until all 27 jobs are captured. No consolidation proposals should be made before the registry is complete.
