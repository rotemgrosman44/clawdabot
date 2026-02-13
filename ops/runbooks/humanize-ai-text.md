# humanize-ai-text Controlled Install + Design-Only Integration (2026-02-13)

## Scope

- Install pinned artifact as runtime skill:
  `/home/rotemgrosman/jarvis-stack/jarvis-data/artifacts/humanize/humanize-ai-text-1.0.0.zip`
- Keep scheduler authority unchanged.
- Keep Gmail behavior unchanged.
- Add disabled-by-default editorial toggle only.

## Evidence

- Audit root:
  `/home/rotemgrosman/jarvis-stack/jarvis-data/audit/humanize-ai-text-1.0.0`
- Evidence files:
  - `evidence/01-checksum.txt`
  - `evidence/02-inventory.txt`
  - `evidence/03-risk-scan.txt`
  - `evidence/03b-risk-scan-strict.txt`
  - `evidence/04-runtime-tree.txt`
  - `evidence/05-smoke-output.txt`
  - `evidence/06-toggle.txt`
  - `evidence/05-smoke-detect.txt`
  - `evidence/05-smoke-url-check.txt`

## Installed Runtime Path

- `/home/rotemgrosman/.clawdbot/skills/humanize-ai-text`

## Toggle

Added to:
`/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/config.json`

```json
{
  "editorial": {
    "humanize_ai_text": {
      "enabled": false,
      "mode": "polish"
    }
  }
}
```

## Integration Plan (Design-only, default OFF)

Intended pipeline:

`draft_text -> humanize_pass -> final_text -> Google Docs -> Telegram`

Constraints:

- Run only when `editorial.humanize_ai_text.enabled == true`.
- Keep default `enabled=false`.
- Preserve URLs exactly.
- Must not change Gmail state.
- On transform failure: fallback to original `draft_text`.
- Log `input_path`, `output_path`, and skill version to `jarvis-data/logs/` (no secrets).

## Rollback

1. Keep toggle disabled (`enabled=false`).
2. Remove installed skill directory:
   `/home/rotemgrosman/.clawdbot/skills/humanize-ai-text`
3. Restore config from backup:
   `/home/rotemgrosman/jarvis-stack/jarvis-data/backups/gmail_triage_config_<timestamp>/config.json`
