#!/usr/bin/env python3
"""
Google Workspace smoke test for Jarvis Stack (gogcli-based).

Goals:
- Verify required OAuth scopes are present.
- Optionally create a Drive folder + Google Doc and return a shareable URL.

Safety:
- Default mode is read-only (no writes).
- Never print secrets (no tokens, no keyring env contents).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import time
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
    return re.sub(r"([A-Za-z0-9_-]{20,})", "<redacted>", s)


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
        rc, _out, err = _run(cmd, timeout_s=60)
    except subprocess.TimeoutExpired:
        rc, err = 124, "timeout"

    if rc == 0:
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


def _pick_id(obj: Any) -> Optional[str]:
    if not isinstance(obj, dict):
        return None
    for k in ["id", "fileId", "docId", "folderId"]:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--account", required=True, help="Google account email")
    p.add_argument(
        "--mode",
        default="read",
        choices=["read", "write"],
        help="read=probes only (default), write=create folder+doc",
    )
    p.add_argument(
        "--require",
        default="drive,docs",
        help="Comma-separated required capabilities (default: drive,docs). Options: gmail,drive,docs,sheets,calendar",
    )
    p.add_argument(
        "--drive-scope",
        default="file",
        choices=["file", "readonly", "full"],
        help="Desired Drive scope mode for requirements (default: file)",
    )
    p.add_argument("--drive-parent-id", default="", help="Optional Drive parent folder id (default: root)")
    p.add_argument("--folder-name", default="", help="Folder name (write mode only)")
    p.add_argument("--doc-title", default="", help="Doc title (write mode only)")
    p.add_argument(
        "--out",
        default="",
        help="Output artifact path (default: ~/jarvis-stack/jarvis-data/gmail-triage/workspace_smoke.json)",
    )
    args = p.parse_args()

    home = Path(os.environ.get("HOME", "/home/rotemgrosman"))
    out_path = (
        Path(args.out)
        if args.out
        else home / "jarvis-stack" / "jarvis-data" / "gmail-triage" / "workspace_smoke.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(out_path.parent, 0o700)
    except PermissionError:
        pass

    gog = str(home / ".local" / "bin" / "gog")

    t0 = time.monotonic()
    now = _now()

    # Inventory current scopes (safe; no tokens).
    scopes: List[str] = []
    rc_auth, out_auth, _err_auth = _run([gog, "auth", "list", "--json"], timeout_s=30)
    if rc_auth == 0:
        try:
            data = json.loads(out_auth)
            for acct in data.get("accounts") or []:
                if str(acct.get("email") or "") == args.account:
                    scopes = list(acct.get("scopes") or [])
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
    required_scopes_by_cap: Dict[str, List[str]] = {
        "gmail": [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.settings.basic",
            "https://www.googleapis.com/auth/gmail.settings.sharing",
        ],
        "drive": [drive_scope],
        "docs": [drive_scope, "https://www.googleapis.com/auth/documents"],
        "sheets": [drive_scope, "https://www.googleapis.com/auth/spreadsheets"],
        "calendar": ["https://www.googleapis.com/auth/calendar"],
    }

    required_caps = [c.strip() for c in args.require.split(",") if c.strip()]
    required_caps = [c for c in required_caps if c in required_scopes_by_cap]

    current_set = set(scopes)
    missing_scopes: Dict[str, List[str]] = {
        cap: [s for s in required_scopes_by_cap[cap] if s not in current_set] for cap in required_caps
    }

    created: Dict[str, Any] = {"folder": None, "doc": None, "doc_url": None}

    if args.mode == "write":
        # Writes are explicit and should only be used after scopes are granted.
        folder_name = args.folder_name or f"Jarvis Smoke {now:%Y-%m-%d %H:%M}"
        doc_title = args.doc_title or f"Jarvis Smoke Doc {now:%Y-%m-%d %H:%M}"

        mkdir_cmd = [gog, "drive", "mkdir", folder_name, "--account", args.account, "--json"]
        if args.drive_parent_id:
            mkdir_cmd.extend(["--parent", args.drive_parent_id])
        rc_m, out_m, err_m = _run(mkdir_cmd, timeout_s=60)
        if rc_m != 0:
            created["folder"] = {
                "ok": False,
                "rc": rc_m,
                "reason": _classify_error(err_m, rc_m),
                "stderr_1": _redact((err_m.strip().splitlines()[:1] or [""])[0])[:200],
            }
        else:
            folder_obj = {}
            try:
                folder_obj = json.loads(out_m)
            except Exception:
                folder_obj = {}
            folder_id = _pick_id(folder_obj)
            created["folder"] = {"ok": True, "id": folder_id}

            create_doc_cmd = [gog, "docs", "create", doc_title, "--account", args.account, "--json"]
            if folder_id:
                create_doc_cmd.extend(["--parent", folder_id])
            rc_d, out_d, err_d = _run(create_doc_cmd, timeout_s=60)
            if rc_d != 0:
                created["doc"] = {
                    "ok": False,
                    "rc": rc_d,
                    "reason": _classify_error(err_d, rc_d),
                    "stderr_1": _redact((err_d.strip().splitlines()[:1] or [""])[0])[:200],
                }
            else:
                doc_obj = {}
                try:
                    doc_obj = json.loads(out_d)
                except Exception:
                    doc_obj = {}
                doc_id = _pick_id(doc_obj)
                created["doc"] = {"ok": True, "id": doc_id}

                if doc_id:
                    rc_u, out_u, err_u = _run([gog, "drive", "url", doc_id, "--account", args.account, "--json"])
                    if rc_u == 0:
                        try:
                            url_obj = json.loads(out_u)
                            created["doc_url"] = url_obj.get("url") or url_obj.get("webViewLink") or None
                        except Exception:
                            created["doc_url"] = None
                    else:
                        created["doc_url"] = None

    artifact = {
        "generated_at": now.isoformat(),
        "account": args.account,
        "mode": args.mode,
        "requirements": {
            "required_caps": required_caps,
            "drive_scope_mode": args.drive_scope,
            "missing_scopes": missing_scopes,
        },
        "duration_ms": int((time.monotonic() - t0) * 1000),
        "oauth_scopes": scopes,
        "probes": probes,
        "created": created,
        "notes": [
            "This script does not modify Gmail.",
            "Docs styling (RTL, Heebo) is not performed here; it requires Docs API batchUpdate support.",
        ],
    }

    _atomic_write_json(out_path, artifact, mode=0o600)

    probe_by_service = {p["service"]: p for p in probes}
    ok = True
    # Scopes must be present.
    if any(missing_scopes.get(cap) for cap in required_caps):
        ok = False
    # Probes must pass for the required services that we can probe.
    for cap in required_caps:
        if cap in ["gmail", "drive", "calendar"]:
            if not probe_by_service.get(cap, {}).get("ok"):
                ok = False
    # In write mode, docs must also be creatable if required.
    if args.mode == "write":
        if "drive" in required_caps and not (created.get("folder") or {}).get("ok"):
            ok = False
        if "docs" in required_caps and not (created.get("doc") or {}).get("ok"):
            ok = False

    print(json.dumps({"ok": bool(ok), "out": str(out_path)}), flush=True)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
