# Editorial Polish HE Runbook

## Contract

- Input: UTF-8 draft markdown/text.
- Output: UTF-8 polished markdown/text.
- URLs preserved exactly.
- No Gmail writes. No network.

## Invocation

```bash
python3 /home/rotemgrosman/.clawdbot/skills/editorial-polish-he/scripts/polish.py -i draft.md -o final.md
```

Telegram short notice:

```bash
python3 /home/rotemgrosman/.clawdbot/skills/editorial-polish-he/scripts/polish.py \
  -i final.md --format telegram --doc-link "https://docs.google.com/..." -o telegram.txt
```

## Integration Design (no workflow patch in this PRD)

Pipeline target:

`draft_text -> editorial_polish_he -> final_text -> Google Docs -> Telegram`

Guardrails:

- Apply only at final-output stage.
- Keep disabled by default until explicit workflow toggle PRD.
- Keep scheduler authority unchanged.
