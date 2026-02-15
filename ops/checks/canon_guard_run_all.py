#!/usr/bin/env python3
from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canon_guard_artifacts import run as run_artifacts
from canon_guard_lib import (
    atomic_write_json,
    atomic_write_text,
    md_codeblock,
    md_section,
    status_rollup,
    utc_now_iso,
    utc_now_ts,
)
from canon_guard_scheduler import run as run_scheduler
from canon_guard_workflows import run as run_workflows
from conflicting_instructions_report import run as run_conflicts
from canon_hygiene_report import run as run_hygiene
from dead_files_report import run as run_dead_files


JARVIS_DATA = Path("/home/rotemgrosman/jarvis-stack/jarvis-data")
AUDIT_ROOT = JARVIS_DATA / "audit"


def run(out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    parts: List[Dict[str, Any]] = []

    scheduler = run_scheduler(out_dir)
    parts.append({"id": "scheduler", "status": scheduler["overall_status"], "report": "scheduler_guard_report.json"})

    workflows = run_workflows(out_dir)
    parts.append({"id": "workflows", "status": workflows["overall_status"], "report": "workflows_sot_report.json"})

    artifacts = run_artifacts(out_dir)
    parts.append({"id": "artifacts", "status": artifacts["overall_status"], "report": "artifacts_contract_report.json"})

    # Analysis outputs (always produced; do not affect PASS/FAIL rollup)
    run_dead_files(out_dir)
    conflicts = run_conflicts(out_dir)
    run_hygiene(out_dir)

    # Conflicts are part of the rollup: any P0 is FAIL.
    c_list = conflicts.get("conflicts") if isinstance(conflicts, dict) else []
    severities = [str(c.get("severity") or "") for c in c_list] if isinstance(c_list, list) else []
    if any(s == "P0" for s in severities):
        c_status = "FAIL"
    elif len(severities) > 0:
        c_status = "WARN"
    else:
        c_status = "PASS"
    parts.append({"id": "conflicts", "status": c_status, "report": "conflicting_instructions_report.json"})

    overall = status_rollup([p["status"] for p in parts])

    report = {
        "kind": "canon_guard",
        "generated_at": utc_now_iso(),
        "overall_status": overall,
        "out_dir": str(out_dir),
        "parts": parts,
        "notes": [
            "Overall status is a rollup of scheduler/workflows/artifacts/conflicts checks.",
            "dead_files_report.* and canon_hygiene_report.* are informational and not included in the rollup.",
            "conflicting_instructions_report.* is included via the conflicts part (P0 => FAIL; otherwise WARN/PASS).",
        ],
    }

    md = "# Canon Guard Report\n\n"
    md += md_section("Overall", f"- status: `{overall}`\n- generated_at: `{report['generated_at']}`\n- out_dir: `{out_dir}`")
    md += md_section(
        "Parts",
        md_codeblock("\n".join([f"{p['status']}\t{p['id']}\t{p['report']}" for p in parts])),
    )
    md += md_section(
        "Additional Outputs",
        "\n".join(
            [
                "- `dead_files_report.md` / `dead_files_report.json`",
                "- `conflicting_instructions_report.md` / `conflicting_instructions_report.json`",
                "- `canon_hygiene_report.md` / `canon_hygiene_report.json`",
            ]
        ),
    )

    atomic_write_json(out_dir / "canon_guard_report.json", report)
    atomic_write_text(out_dir / "canon_guard_report.md", md)

    # Update stable pointers (audit-only state).
    try:
        AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
        latest_link = AUDIT_ROOT / "canon-guard-latest"
        baseline_link = AUDIT_ROOT / "canon-guard-baseline"
        tmp = AUDIT_ROOT / f".canon-guard-latest.tmp.{os.getpid()}"
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
        os.symlink(str(out_dir), str(tmp))
        os.replace(str(tmp), str(latest_link))

        # Baseline pointer: only advance on PASS (never on WARN/FAIL).
        baseline_path = ""
        if baseline_link.exists() or baseline_link.is_symlink():
            try:
                baseline_path = str(baseline_link.resolve())
            except Exception:
                baseline_path = ""
        if overall == "PASS":
            tmp_b = AUDIT_ROOT / f".canon-guard-baseline.tmp.{os.getpid()}"
            if tmp_b.exists() or tmp_b.is_symlink():
                tmp_b.unlink()
            os.symlink(str(out_dir), str(tmp_b))
            os.replace(str(tmp_b), str(baseline_link))
            baseline_path = str(out_dir)

        atomic_write_json(
            AUDIT_ROOT / "canon-guard-index.json",
            {
                "latest": str(out_dir),
                "baseline": baseline_path,
                "generated_at": report["generated_at"],
                "overall_status": overall,
            },
        )
    except Exception:
        # Index update is best-effort and must not break the core checks.
        pass

    return report


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out-dir",
        default="",
        help="Output directory (default: /home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-guard-<timestamp>/)",
    )
    args = ap.parse_args()
    out = Path(args.out_dir) if args.out_dir else (JARVIS_DATA / "audit" / f"canon-guard-{utc_now_ts()}")
    rep = run(out)
    raise SystemExit(0 if rep.get("overall_status") in ("PASS", "WARN") else 2)
