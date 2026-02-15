#!/usr/bin/env python3
from __future__ import annotations

import sys
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canon_guard_lib import (
    atomic_write_json,
    atomic_write_text,
    md_codeblock,
    md_section,
    run_cmd,
    utc_now_iso,
)


REPO_ROOT = Path("/home/rotemgrosman/jarvis-stack/jarvis/clawdbot")
SCRIPTS_DIR = REPO_ROOT / "scripts"
SYSTEMD_USER_DIR = Path("/home/rotemgrosman/.config/systemd/user")
CRON_STORE = Path("/home/rotemgrosman/.clawdbot/cron/jobs.json")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _list_py_scripts() -> List[Path]:
    return sorted([p for p in SCRIPTS_DIR.glob("*.py") if p.is_file()])


def _systemd_unit_texts() -> str:
    txt = ""
    for p in sorted(SYSTEMD_USER_DIR.glob("clawdbot-*.service")) + sorted(SYSTEMD_USER_DIR.glob("clawdbot-*.timer")):
        if p.is_file():
            txt += f"\n# {p}\n"
            txt += _read_text(p)
    return txt


def _cron_payload_text() -> str:
    if not CRON_STORE.exists():
        return ""
    try:
        data = json.loads(_read_text(CRON_STORE))
    except Exception:
        return _read_text(CRON_STORE)
    out = []
    if isinstance(data, dict) and isinstance(data.get("jobs"), list):
        for j in data["jobs"]:
            if not isinstance(j, dict):
                continue
            payload = j.get("payload")
            if isinstance(payload, dict):
                for k in ("message", "text"):
                    v = payload.get(k)
                    if isinstance(v, str) and v.strip():
                        out.append(v)
    return "\n".join(out)


def _imports_text(paths: List[Path]) -> str:
    # Heuristic: grep import lines for local script basenames.
    # This is evidence-based but not a full call graph.
    buf = []
    for p in paths:
        try:
            for line in _read_text(p).splitlines():
                if line.startswith("import ") or line.startswith("from "):
                    buf.append(line)
        except Exception:
            continue
    return "\n".join(buf)


def run(out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    scripts = _list_py_scripts()
    systemd_txt = _systemd_unit_texts()
    cron_txt = _cron_payload_text()
    imports_txt = _imports_text(scripts)

    atomic_write_text(out_dir / "dead_files_evidence_systemd_units.txt", systemd_txt)
    atomic_write_text(out_dir / "dead_files_evidence_cron_payloads.txt", cron_txt)
    atomic_write_text(out_dir / "dead_files_evidence_imports.txt", imports_txt)

    referenced: Set[str] = set()

    def note_ref(s: str) -> None:
        if s:
            referenced.add(s)

    # Evidence-based reference detection: exact script basenames + full repo paths.
    for p in scripts:
        bn = p.name
        full = str(p)
        if bn in systemd_txt or full in systemd_txt:
            note_ref(bn)
        if bn in cron_txt or full in cron_txt:
            note_ref(bn)
        if bn.replace(".py", "") in imports_txt:
            note_ref(bn)

    items: List[Dict[str, Any]] = []
    for p in scripts:
        bn = p.name
        used = bn in referenced
        # Confidence: high when not referenced anywhere; lower when name suggests manual tool.
        manual_hint = bool(re.search(r"(validate|probe|publish|smoke|scope|watch)", bn))
        confidence = 0.85 if (not used and not manual_hint) else (0.55 if not used else 0.1)
        items.append(
            {
                "path": str(p),
                "referenced_by": {
                    "systemd": bn in systemd_txt or str(p) in systemd_txt,
                    "cron_payload": bn in cron_txt or str(p) in cron_txt,
                    "imports": bn.replace(".py", "") in imports_txt,
                },
                "status": "UNREFERENCED" if not used else "REFERENCED",
                "confidence_unreferenced": confidence if not used else 0.0,
            }
        )

    unref = [it for it in items if it["status"] == "UNREFERENCED"]

    report = {
        "kind": "dead_files_report",
        "generated_at": utc_now_iso(),
        "scope": {
            "scripts_dir": str(SCRIPTS_DIR),
            "systemd_user_dir": str(SYSTEMD_USER_DIR),
            "cron_store": str(CRON_STORE),
        },
        "summary": {"scripts_total": len(items), "unreferenced": len(unref)},
        "items": items,
    }

    md = "# Dead Files Report (Gmail Plumber Scope)\n\n"
    md += md_section(
        "Summary",
        "\n".join(
            [
                f"- scripts_total: `{len(items)}`",
                f"- unreferenced: `{len(unref)}`",
                "- evidence sources: systemd unit texts, cron payload texts, import lines",
            ]
        ),
    )
    md += md_section(
        "Unreferenced Scripts",
        md_codeblock("\n".join([f"{it['confidence_unreferenced']:.2f}\t{it['path']}" for it in sorted(unref, key=lambda x: -x["confidence_unreferenced"])])),
    )

    atomic_write_json(out_dir / "dead_files_report.json", report)
    atomic_write_text(out_dir / "dead_files_report.md", md)
    return report


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="", help="Output directory (default: current working dir)")
    args = ap.parse_args()
    out = Path(args.out_dir) if args.out_dir else Path.cwd()
    run(out)
    raise SystemExit(0)
