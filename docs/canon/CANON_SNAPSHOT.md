# Bot #4 — CANON_SNAPSHOT.md (Read-only reference for Codex)

## Purpose
This file is a minimal, repo-local reference so Codex always has at least one canonical anchor.
The authoritative operational canon lives in the Ubuntu runtime data directory (outside the code repo).

## Source of Truth (Ubuntu runtime)
Authoritative canon directory (Ubuntu VM):
- /home/rotemgrosman/jarvis-stack/jarvis-data/memory/canon/

Host-mapped view (macOS via OrbStack):
- /Users/rotemgrosman/OrbStack/ubuntu/home/rotemgrosman/jarvis-stack/jarvis-data/memory/canon/

## Canon Policy
- Canon is edited and maintained in the runtime canon directory (Ubuntu VM), not in the code repo.
- This repo file must never become a competing source of truth.
- If updated, it should be refreshed from the runtime canon (copy/refresh), not diverge.

## Canon Files (Conceptual Set)
The canonical set is:
- STATUS.md (current state)
- RUNBOOKS.md (procedures)
- POSTMORTEMS.md (incident learnings)
- CANON_RULES.md (core rules)
- ARCHITECTURE.md (stable system map)

## Guardrails
- Never store secrets in canon or repo docs (api keys, tokens, credentials).
- Do not touch `clawdbot-playground` for operations unless explicitly instructed.

## Operator Note
If Codex cannot access the runtime canon directory directly, use this file as the minimum reference and refresh it manually when needed.