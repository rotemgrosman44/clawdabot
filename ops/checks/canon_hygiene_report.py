#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from canon_guard_lib import (
    atomic_write_json,
    atomic_write_text,
    md_codeblock,
    md_section,
    utc_now_iso,
)


REPO_ROOT = Path("/home/rotemgrosman/jarvis-stack/jarvis/clawdbot")
SYSTEMD_DIR = Path("/home/rotemgrosman/.config/systemd/user")
CRON_STORE = Path("/home/rotemgrosman/.clawdbot/cron/jobs.json")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _git(cmd: List[str]) -> Tuple[int, str, str]:
    proc = subprocess.run(cmd, text=True, capture_output=True, cwd=str(REPO_ROOT))
    return proc.returncode, proc.stdout, proc.stderr


def _systemd_exec_paths() -> Set[str]:
    paths: Set[str] = set()
    for p in sorted(SYSTEMD_DIR.glob("clawdbot-*.service")):
        if not p.is_file():
            continue
        txt = _read_text(p)
        for line in txt.splitlines():
            if line.strip().startswith("ExecStart="):
                rhs = line.split("=", 1)[1] if "=" in line else line
                for tok in rhs.strip().split():
                    tok = tok.strip().strip('"')
                    if tok.startswith(str(REPO_ROOT) + "/"):
                        paths.add(tok)
    return paths


def _cron_payload_paths() -> Set[str]:
    paths: Set[str] = set()
    if not CRON_STORE.exists():
        return paths
    try:
        data = json.loads(_read_text(CRON_STORE))
    except Exception:
        return paths
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        return paths
    for j in jobs:
        if not isinstance(j, dict):
            continue
        payload = j.get("payload")
        if not isinstance(payload, dict):
            continue
        s = ""
        if isinstance(payload.get("message"), str):
            s += payload["message"] + "\n"
        if isinstance(payload.get("text"), str):
            s += payload["text"] + "\n"
        for tok in s.split():
            tok = tok.strip().strip('"')
            if tok.startswith(str(REPO_ROOT) + "/"):
                # Strip common trailing punctuation.
                tok = tok.rstrip(").,;")
                paths.add(tok)
    return paths


def run(out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    sysd = sorted(_systemd_exec_paths())
    cron = sorted(_cron_payload_paths())
    referenced = sorted(set(sysd) | set(cron))

    rc_h, head, _ = _git(["git", "rev-parse", "HEAD"])
    head = head.strip() if rc_h == 0 else ""

    rc_s, status, _ = _git(["git", "status", "--porcelain"])
    status_lines = [ln for ln in status.splitlines() if ln.strip()] if rc_s == 0 else []

    # Map dirty paths (best effort). git status lines look like: " M path" or "?? path".
    dirty: List[str] = []
    for ln in status_lines:
        p = ln[3:].strip()
        if not p:
            continue
        abs_p = str((REPO_ROOT / p).resolve())
        if abs_p in referenced:
            dirty.append(abs_p)

    report = {
        "kind": "canon_hygiene_report",
        "generated_at": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "git_head": head,
        "referenced_paths": referenced,
        "referenced_by": {"systemd_execstart": sysd, "cron_payloads": cron},
        "dirty_referenced_paths": sorted(set(dirty)),
        "notes": [
            "This report is informational and does not affect canon_guard rollup status.",
            "Dirty referenced paths imply 'reviewed source != runtime behavior' risk if services are restarted.",
        ],
    }

    md = "# Canon Hygiene Report\n\n"
    md += md_section("Repo", f"- root: `{REPO_ROOT}`\n- HEAD: `{head or 'unknown'}`")
    md += md_section(
        "Referenced Runtime Paths",
        md_codeblock("\n".join(referenced) if referenced else "(none detected)"),
    )
    md += md_section(
        "Dirty Referenced Paths",
        md_codeblock("\n".join(sorted(set(dirty))) if dirty else "(none)"),
    )

    atomic_write_json(out_dir / "canon_hygiene_report.json", report)
    atomic_write_text(out_dir / "canon_hygiene_report.md", md)
    return report


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="", help="Output directory (default: current working dir)")
    args = ap.parse_args()
    out = Path(args.out_dir) if args.out_dir else Path.cwd()
    run(out)
    raise SystemExit(0)
