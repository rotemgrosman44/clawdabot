#!/usr/bin/env python3
from __future__ import annotations

import sys
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canon_guard_lib import (
    atomic_write_json,
    atomic_write_text,
    md_codeblock,
    md_section,
    read_text_safe,
    run_cmd,
    utc_now_iso,
)


REPO_ROOT = Path("/home/rotemgrosman/jarvis-stack/jarvis/clawdbot")
DOCS_CANON_DIR = REPO_ROOT / "docs" / "canon"
DOCS_GOV_CANON_DIR = REPO_ROOT / "docs" / "governance" / "canon"
JARVIS_DATA = Path("/home/rotemgrosman/jarvis-stack/jarvis-data")
GMAIL_CFG = JARVIS_DATA / "gmail-triage" / "config.json"


def _find_lines(path: Path, pattern: str) -> List[int]:
    if not path.exists():
        return []
    rx = re.compile(pattern)
    lines = read_text_safe(path).splitlines()
    out = []
    for i, line in enumerate(lines, start=1):
        if rx.search(line):
            out.append(i)
    return out


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_systemd_unit_text(unit: str) -> str:
    res = run_cmd(["systemctl", "--user", "cat", unit], timeout_s=20)
    return (res.stdout + ("\n" + res.stderr if res.stderr else "")).strip()


def run(out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    conflicts: List[Dict[str, Any]] = []

    # Conflict 1: Safety doc claims read-only vs runtime config allowing writes.
    cfg = _read_json(GMAIL_CFG) if GMAIL_CFG.exists() else {}
    write_enabled = bool(((cfg.get("write") or {}).get("enabled")) if isinstance(cfg, dict) else False)
    allowed_actions = []
    try:
        allowed_actions = list((((cfg.get("write") or {}).get("policy") or {}).get("allowedActions") or []))
    except Exception:
        allowed_actions = []

    canon_safety_doc = DOCS_CANON_DIR / "GMAIL_TRIAGE_SAFETY.md"
    # Evidence-based: this doc contains hard statements like "No label changes" / "No trash".
    read_only_claim_lines = []
    for pat in [r"No destructive", r"No label", r"No trash", r"No modify", r"Hooks remain disabled"]:
        read_only_claim_lines += _find_lines(canon_safety_doc, pat)
    read_only_claim_lines = sorted(set(read_only_claim_lines))

    if canon_safety_doc.exists() and read_only_claim_lines and write_enabled:
        conflicts.append(
            {
                "id": "safety_doc_vs_config_writes",
                "severity": "P0",
                "a": {"path": str(canon_safety_doc), "lines": read_only_claim_lines},
                "b": {
                    "path": str(GMAIL_CFG),
                    "values": {"write.enabled": write_enabled, "write.policy.allowedActions": allowed_actions},
                },
                "remediation": [
                    "Preferred (SAFE_READONLY canon): set `.write.enabled=false` in jarvis-data/gmail-triage/config.json.",
                    "Alternative (if writes are intended): update docs/canon/GMAIL_TRIAGE_SAFETY.md and docs/governance/canon/SAFETY.md to match live config (not recommended).",
                ],
                "resolution_applied": "none (report only)",
            }
        )

    # Conflict 2: Scheduler doc schedule vs actual systemd timer (OnCalendar).
    sched_doc = DOCS_CANON_DIR / "GMAIL_TRIAGE_SCHEDULER.md"
    timer_path = Path("/home/rotemgrosman/.config/systemd/user/clawdbot-gmail-triage.timer")
    timer_text = timer_path.read_text(encoding="utf-8", errors="replace") if timer_path.exists() else ""
    oncal_line = ""
    for line in timer_text.splitlines():
        if line.strip().startswith("OnCalendar="):
            oncal_line = line.strip()
            break

    # Evidence-based: doc suggests multiple daily times (09/12/15/18) in this stack.
    doc_time_lines = _find_lines(sched_doc, r"(09:00|12:00|15:00|18:00)")
    if sched_doc.exists() and doc_time_lines and oncal_line and "14:00:00" in oncal_line:
        conflicts.append(
            {
                "id": "scheduler_doc_vs_timer_oncalendar",
                "severity": "P1",
                "a": {"path": str(sched_doc), "lines": doc_time_lines},
                "b": {"path": str(timer_path), "oncalendar": oncal_line},
                "remediation": [
                    "Update docs/canon/GMAIL_TRIAGE_SCHEDULER.md to match the real systemd timer schedule.",
                    "Do not change the timer in governance work unless explicitly approved.",
                ],
                "resolution_applied": "none (report only)",
            }
        )

    # Conflict 3: Newsletter-weekly standard vs current runtime (missing latest symlink).
    # This is a governance non-compliance until Phase B, but still a cross-doc mismatch if docs claim it's canonical already.
    legacy_dir = JARVIS_DATA / "newsletter-weekly"
    latest_link = legacy_dir / "latest"
    if DOCS_GOV_CANON_DIR.exists():
        artifacts_doc = DOCS_GOV_CANON_DIR / "ARTIFACTS.md"
        # Look for "latest ->" mention.
        latest_doc_lines = _find_lines(artifacts_doc, r"newsletter-weekly/latest")
        if artifacts_doc.exists() and latest_doc_lines and not latest_link.exists():
            conflicts.append(
                {
                    "id": "newsletter_latest_missing_vs_governance_standard",
                    "severity": "P1",
                    "a": {"path": str(artifacts_doc), "lines": latest_doc_lines},
                    "b": {"path": str(latest_link), "exists": False},
                    "remediation": [
                        "Create newsletter-weekly latest via scripts/newsletter_weekly_pipeline.py (no Drive publish).",
                        "After a PASS run, replace legacy flat outputs with symlinks into latest.",
                    ],
                    "resolution_applied": "none (Phase B required)",
                }
            )

    report = {
        "kind": "conflicting_instructions_report",
        "generated_at": utc_now_iso(),
        "conflicts": conflicts,
        "counts": {"total": len(conflicts)},
    }

    md = "# Conflicting Instructions Report\n\n"
    md += md_section("Summary", f"- conflicts: `{len(conflicts)}`\n- generated_at: `{report['generated_at']}`")
    if conflicts:
        lines = []
        for c in conflicts:
            lines.append(f"{c['severity']}\t{c['id']}\tA={c['a']['path']}\tB={c['b']['path']}")
        md += md_section("Conflicts", md_codeblock("\n".join(lines)))
        # Remediation appendix (actionable but non-executing).
        for c in conflicts:
            rem = c.get("remediation")
            if isinstance(rem, list) and rem:
                md += md_section(
                    f"Remediation: {c.get('id')}",
                    "\n".join([f"- {str(x)}" for x in rem]),
                )
    else:
        md += md_section("Conflicts", "None detected by this targeted checker.")

    atomic_write_json(out_dir / "conflicting_instructions_report.json", report)
    atomic_write_text(out_dir / "conflicting_instructions_report.md", md)
    return report


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="", help="Output directory (default: current working dir)")
    args = ap.parse_args()
    out = Path(args.out_dir) if args.out_dir else Path.cwd()
    run(out)
    raise SystemExit(0)
