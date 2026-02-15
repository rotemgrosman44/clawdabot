#!/usr/bin/env python3
"""
PRD v13.0 - Newsletter Weekly pipeline (build + validate + archive).

This script is intentionally local-first and deterministic:
- Reads only local upstream reports produced by the systemd Newsletter Master job
  (scripts/gmail_triage_poll.py --mode newsletter-weekly).
- Produces a per-run archive folder under jarvis-data/archive/newsletter-weekly/YYYY/MM/week-YYYY-WW/run-<ts>/.
- Mirrors latest via symlink: jarvis-data/newsletter-weekly/latest -> <run_dir>.

It does NOT send Telegram by itself.
Drive publishing is implemented as an optional step but should be executed only
when explicitly enabled and after operator validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple
from zoneinfo import ZoneInfo


DEFAULT_TZ = "Asia/Jerusalem"
DEFAULT_PROBE = Path("/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/newsletter_weekly_probe.py")
DEFAULT_VALIDATE = Path("/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/brief_validate.py")

JARVIS_DATA = Path("/home/rotemgrosman/jarvis-stack/jarvis-data")
LATEST_LINK = JARVIS_DATA / "newsletter-weekly" / "latest"
ARCHIVE_ROOT = JARVIS_DATA / "archive" / "newsletter-weekly"


def _run(cmd: list[str], *, timeout_s: int = 300) -> Tuple[int, str, str]:
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_s)
    return proc.returncode, proc.stdout, proc.stderr


def _atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, mode)
    except PermissionError:
        pass
    os.replace(tmp, path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_symlink(target: Path, link_path: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_link = link_path.with_name(link_path.name + f".tmp.{os.getpid()}")
    try:
        if tmp_link.exists() or tmp_link.is_symlink():
            tmp_link.unlink()
        tmp_link.symlink_to(target)
        os.replace(tmp_link, link_path)
    finally:
        try:
            if tmp_link.exists() or tmp_link.is_symlink():
                tmp_link.unlink()
        except Exception:
            pass


def _compute_paths(now: datetime) -> Tuple[Path, str, str]:
    year = now.strftime("%Y")
    month = now.strftime("%m")
    week_id = now.strftime("%G-W%V")
    run_ts = now.strftime("%Y%m%dT%H%M%S")
    run_dir = ARCHIVE_ROOT / year / month / f"week-{week_id}" / f"run-{run_ts}"
    return run_dir, week_id, run_ts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tz", default=DEFAULT_TZ)
    ap.add_argument("--account", default="grosmanrotem@gmail.com")
    ap.add_argument("--probe", default=str(DEFAULT_PROBE))
    ap.add_argument("--validator", default=str(DEFAULT_VALIDATE))
    ap.add_argument("--min-items", type=int, default=10)
    ap.add_argument("--max-items", type=int, default=15)
    ap.add_argument(
        "--enable-drive-publish",
        action="store_true",
        help="If set, run drive publisher after building report.md (external side effects).",
    )
    ap.add_argument(
        "--drive-publisher",
        default="/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/drive_publish_newsletter_weekly.py",
    )
    args = ap.parse_args()

    tz = ZoneInfo(str(args.tz))
    now = datetime.now(tz=tz)

    run_dir, week_id, run_ts = _compute_paths(now)
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(run_dir, 0o700)
    except PermissionError:
        pass

    # Build canonical artifacts into the run_dir.
    probe_cmd = [
        "/usr/bin/python3",
        str(Path(args.probe)),
        "--tz",
        str(args.tz),
        "--out-dir",
        str(run_dir),
        "--min-items",
        str(args.min_items),
        "--max-items",
        str(args.max_items),
    ]
    rc_p, out_p, err_p = _run(probe_cmd, timeout_s=300)
    _atomic_write_text(run_dir / "probe.txt", f"rc={rc_p}\n{out_p}{err_p}", mode=0o600)

    # Optional external step (Drive). Kept behind explicit flag.
    drive_meta: Dict[str, Any] = {}
    if args.enable_drive_publish:
        pub_cmd = [
            "/usr/bin/python3",
            str(Path(args.drive_publisher)),
            "--account",
            str(args.account),
            "--week-id",
            week_id,
            "--date",
            now.date().isoformat(),
            "--in-md",
            str(run_dir / "report.md"),
            "--out-json",
            str(run_dir / "drive_doc.json"),
        ]
        rc_d, out_d, err_d = _run(pub_cmd, timeout_s=300)
        _atomic_write_text(run_dir / "drive_publish.txt", f"rc={rc_d}\n{out_d}{err_d}", mode=0o600)
        if (run_dir / "drive_doc.json").exists():
            try:
                drive_meta = _read_json(run_dir / "drive_doc.json")
            except Exception:
                drive_meta = {}

    # Validate contract and required fields.
    message = run_dir / "telegram_message.txt"
    signals = run_dir / "signals.json"
    report = run_dir / "report.json"

    # Write evidence.json (inputs + upstream provenance) for auditability.
    evidence: Dict[str, Any] = {
        "kind": "newsletter_weekly_evidence",
        "generated_at": now.isoformat(),
        "week_id": week_id,
        "run_dir": str(run_dir),
        "inputs": {
            "upstream_report": "",
            "upstream_report_sha256": "",
            "probe_script": str(Path(args.probe)),
            "validator_script": str(Path(args.validator)),
        },
        "outputs": {
            "telegram_message": str(message),
            "signals": str(signals),
            "report_json": str(report),
            "report_md": str(run_dir / "report.md"),
        },
    }
    # If the probe already produced report.json, use it to record upstream report path/hash.
    try:
        if report.exists():
            rep = _read_json(report)
            if isinstance(rep, dict):
                upstream = str(rep.get("upstream_report") or "").strip()
                if upstream:
                    evidence["inputs"]["upstream_report"] = upstream
                    up_path = Path(upstream)
                    if up_path.exists() and up_path.is_file():
                        evidence["inputs"]["upstream_report_sha256"] = _sha256_file(up_path)
    except Exception:
        pass
    _atomic_write_text(run_dir / "evidence.json", json.dumps(evidence, ensure_ascii=True, indent=2) + "\n", mode=0o600)

    # Compatibility alias: message.txt -> telegram_message.txt (symlink).
    try:
        if message.exists():
            alias = run_dir / "message.txt"
            if alias.exists() or alias.is_symlink():
                alias.unlink()
            os.symlink("telegram_message.txt", str(alias))
    except Exception:
        pass

    validate_cmd = [
        "/usr/bin/python3",
        str(Path(args.validator)),
        "--product",
        "NEWSLETTER",
        "--product-token",
        "NEWSLETTER_WEEKLY",
        "--lines-exact",
        "6",
        "--require-signal-prefix",
        "SIGNAL NW|",
        "--signal-max-len",
        "120",
        "--message",
        str(message),
        "--signals",
        str(signals),
        "--report",
        str(report),
        "--require-report-url",
        "--min-report-items",
        str(args.min_items),
        "--require-top3",
    ]
    rc_v, out_v, err_v = _run(validate_cmd, timeout_s=60)
    _atomic_write_text(run_dir / "validator.txt", f"rc={rc_v}\n{out_v}{err_v}", mode=0o600)

    # Mirror latest only on PASS.
    if rc_v == 0:
        _safe_symlink(run_dir, LATEST_LINK)

    # Provide a compact run manifest (no secrets).
    manifest = {
        "product": "NEWSLETTER_WEEKLY",
        "week_id": week_id,
        "run_ts": run_ts,
        "run_dir": str(run_dir),
        "probe_rc": rc_p,
        "validator_rc": rc_v,
        "drive_enabled": bool(args.enable_drive_publish),
        "drive_doc_id": str(drive_meta.get("doc_id") or ""),
        "drive_url": str(drive_meta.get("url") or ""),
        "latest_link": str(LATEST_LINK),
    }
    _atomic_write_text(run_dir / "run_manifest.json", json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", mode=0o600)

    return 0 if rc_v == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
