#!/usr/bin/env python3
"""
Generate a read-only OAuth scope and service probe matrix for `gog`.

Design:
- No secrets printed.
- Only read-only probes.
- Write a JSON artifact under jarvis-data for auditability.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone()


def _atomic_write_json(path: Path, data: Any, mode: int = 0o600) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(path)


def _run(cmd: List[str], timeout_s: int = 60) -> Tuple[int, str, str]:
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_s)
    return proc.returncode, proc.stdout, proc.stderr


def _redact(s: str) -> str:
    # Best-effort redaction for long opaque tokens that sometimes appear in URLs.
    s = re.sub(r"([A-Za-z0-9_-]{20,})", "<redacted>", s)
    return s


def _classify_error(stderr: str, rc: int) -> str:
    low = stderr.lower()
    if rc == 127 or "unknown command" in low:
        return "unsupported"
    if "insufficient" in low and "scope" in low:
        return "missing_scope"
    if "scope" in low and "not granted" in low:
        return "missing_scope"
    if "has not been used" in low and "enabled" in low:
        return "api_not_enabled"
    if "permission" in low or "forbidden" in low:
        return "permission_denied"
    if rc == 124:
        return "timeout"
    return "error"


def _probe(name: str, cmd: List[str]) -> Dict[str, Any]:
    try:
        rc, out, err = _run(cmd, timeout_s=60)
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", "timeout"

    if rc == 0:
        # Do not return stdout (can include private metadata). Keep summary only.
        return {"service": name, "ok": True, "rc": 0}

    err_line = (err.strip().splitlines()[:1] or [""])[0]
    err_line = _redact(err_line)[:200]
    return {
        "service": name,
        "ok": False,
        "rc": rc,
        "reason": _classify_error(err, rc),
        "stderr_1": err_line,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--account", required=True, help="Google account email used for probes")
    p.add_argument(
        "--out",
        default="",
        help="Output path (default: ~/jarvis-stack/jarvis-data/gmail-triage/scope_matrix.json)",
    )
    p.add_argument(
        "--drive-scope",
        default="file",
        choices=["file", "readonly", "full"],
        help="Desired Drive scope mode for requirements calculation (default: file)",
    )
    args = p.parse_args()

    home = Path(os.environ.get("HOME", "/home/rotemgrosman"))
    out_path = (
        Path(args.out)
        if args.out
        else home / "jarvis-stack" / "jarvis-data" / "gmail-triage" / "scope_matrix.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(out_path.parent, 0o700)
    except PermissionError:
        pass

    gog = str(home / ".local" / "bin" / "gog")

    # Scopes inventory (safe subset only).
    rc, out, err = _run([gog, "auth", "list", "--json"], timeout_s=30)
    scopes: List[str] = []
    services: List[str] = []
    if rc == 0:
        try:
            data = json.loads(out)
            for acct in data.get("accounts") or []:
                if str(acct.get("email") or "") == args.account:
                    scopes = list(acct.get("scopes") or [])
                    services = list(acct.get("services") or [])
                    break
        except Exception:
            pass

    probes = [
        _probe("gmail", [gog, "gmail", "labels", "list", "--account", args.account, "--json"]),
        _probe("calendar", [gog, "calendar", "calendars", "--account", args.account, "--json"]),
        _probe("drive", [gog, "drive", "ls", "--account", args.account, "--json", "--max", "1"]),
    ]

    drive_scope = {
        "file": "https://www.googleapis.com/auth/drive.file",
        "readonly": "https://www.googleapis.com/auth/drive.readonly",
        "full": "https://www.googleapis.com/auth/drive",
    }[args.drive_scope]

    required_by_service: Dict[str, List[str]] = {
        "gmail": [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.settings.basic",
            "https://www.googleapis.com/auth/gmail.settings.sharing",
        ],
        "drive": [drive_scope],
        # Docs and Sheets require Drive scope in addition to their API scopes.
        "docs": [drive_scope, "https://www.googleapis.com/auth/documents"],
        "sheets": [drive_scope, "https://www.googleapis.com/auth/spreadsheets"],
        "calendar": ["https://www.googleapis.com/auth/calendar"],
    }

    current_set = set(scopes)
    missing_by_service = {
        svc: [s for s in req if s not in current_set] for svc, req in required_by_service.items()
    }

    matrix = {
        "generated_at": _now().isoformat(),
        "account": args.account,
        "gog_version": None,  # populated below (best-effort)
        "oauth": {"services": services, "scopes": scopes},
        "requirements": {
            "drive_scope_mode": args.drive_scope,
            "required_scopes": required_by_service,
            "missing_scopes": missing_by_service,
        },
        "probes": probes,
        "notes": [
            "Docs/Sheets/Slides generally require Drive scopes; probe drive first.",
            "Maps/Places uses API keys (not OAuth) and is out of gog scope matrix.",
            "YouTube is not probed here; depends on additional scopes and gog support.",
        ],
    }

    rc_v, out_v, _err_v = _run([gog, "version", "--json"], timeout_s=10)
    if rc_v == 0:
        try:
            matrix["gog_version"] = json.loads(out_v)
        except Exception:
            matrix["gog_version"] = None

    _atomic_write_json(out_path, matrix, mode=0o600)

    # Minimal stdout (no scopes printed).
    print(json.dumps({"ok": True, "out": str(out_path), "probes_ok": sum(1 for p in probes if p["ok"])}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
