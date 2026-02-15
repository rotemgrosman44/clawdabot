#!/usr/bin/env python3
"""
Deterministic EOD Summary probe + renderer (PRD v11.0).

Reads (local, read-only):
  - /home/rotemgrosman/second-brain/tasks/today.md
  - /home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports/*.json

Writes (local):
  - /home/rotemgrosman/jarvis-stack/jarvis-data/eod/message.txt
  - /home/rotemgrosman/jarvis-stack/jarvis-data/eod/signals.json

Prints the final Telegram body (12-15 lines, last line SIGNAL JSON) to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_TZ = "Asia/Jerusalem"
EMAIL_FRESHNESS_THRESHOLD_HOURS = 36

DEFAULT_TASKS_PATH = Path("/home/rotemgrosman/second-brain/tasks/today.md")
DEFAULT_GMAIL_REPORTS_DIR = Path(
    "/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports"
)
DEFAULT_OUT_DIR = Path("/home/rotemgrosman/jarvis-stack/jarvis-data/eod")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_json(path: Path, obj: Any) -> None:
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sanitize_token(value: str, *, max_len: int = 140) -> str:
    s = (
        value.replace("|", "/")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("<", "")
        .replace(">", "")
        .strip()
    )
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return "none"
    if len(s) > max_len:
        s = s[: max_len - 3].rstrip() + "..."
    return s


def _status_icon(status: str) -> str:
    s = (status or "").strip().upper()
    if s == "GREEN":
        return "🟢"
    if s == "YELLOW":
        return "🟡"
    if s == "RED":
        return "🔴"
    return "🟡"


def _status_short(status: str) -> str:
    s = (status or "").strip().upper()
    if s == "GREEN":
        return "G"
    if s == "YELLOW":
        return "Y"
    if s == "RED":
        return "R"
    return "Y"


def _pick_latest_report(reports_dir: Path, pattern: str) -> Path | None:
    try:
        candidates = sorted(reports_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    except Exception:
        return None
    return candidates[-1] if candidates else None


def _coerce_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            return int(value.strip())
    except Exception:
        pass
    return 0


@dataclass(frozen=True)
class EmailSignals:
    unread: int
    urgent: int
    invoices: int
    subjects_unread: list[str]
    report_path: str | None
    report_generated_at: str | None
    report_mtime_epoch: float | None


def _extract_email_signals(reports_dir: Path) -> EmailSignals | None:
    triage_report = _pick_latest_report(reports_dir, "gmail-triage-*.json")
    if not triage_report:
        return None

    try:
        mtime = float(triage_report.stat().st_mtime)
    except Exception:
        mtime = None

    data = _read_json(triage_report)
    if not isinstance(data, dict):
        return None

    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    new_threads = data.get("new_threads") if isinstance(data.get("new_threads"), list) else []

    unread_threads = 0
    unread_subjects: list[str] = []
    for t in new_threads:
        if not isinstance(t, dict):
            continue
        labels = t.get("labels")
        is_unread = isinstance(labels, list) and any(str(x) == "UNREAD" for x in labels)
        if is_unread:
            unread_threads += 1
            subj = t.get("subject")
            if isinstance(subj, str) and subj.strip():
                unread_subjects.append(_sanitize_token(subj, max_len=110))

    urgent = _coerce_int(summary.get("urgent"))
    invoices = _coerce_int(summary.get("invoices"))
    generated_at = data.get("generated_at")
    generated_at_str = str(generated_at) if isinstance(generated_at, str) else None

    return EmailSignals(
        unread=int(unread_threads),
        urgent=int(urgent),
        invoices=int(invoices),
        subjects_unread=unread_subjects[:2],
        report_path=str(triage_report),
        report_generated_at=generated_at_str,
        report_mtime_epoch=mtime,
    )


def _extract_tasks_summary(md: str) -> dict[str, Any]:
    open_items: list[str] = []
    done_items: list[str] = []
    for line in md.splitlines():
        m_open = re.match(r"^\s*-\s*\[\s*\]\s+(.*)$", line)
        if m_open:
            open_items.append(_sanitize_token(m_open.group(1), max_len=120))
            continue
        m_done = re.match(r"^\s*-\s*\[\s*[xX]\s*\]\s+(.*)$", line)
        if m_done:
            done_items.append(_sanitize_token(m_done.group(1), max_len=120))
            continue

    return {
        "open_items": open_items,
        "done_items": done_items,
        "open_count": len(open_items),
        "done_count": len(done_items),
        "highlight_done": done_items[0] if done_items else "none",
        "pending_top5": open_items[:5],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tz", default=DEFAULT_TZ)
    ap.add_argument("--tasks", default=str(DEFAULT_TASKS_PATH))
    ap.add_argument("--gmail-reports", default=str(DEFAULT_GMAIL_REPORTS_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()

    tz = ZoneInfo(str(args.tz))
    now = datetime.now(tz=tz)
    date_iso = now.date().isoformat()

    reason_parts: list[str] = []

    tasks_md = _read_text(Path(args.tasks))
    if tasks_md is None:
        reason_parts.append("tasks missing")
        tasks = {
            "open_items": [],
            "done_items": [],
            "open_count": 0,
            "done_count": 0,
            "highlight_done": "none",
            "pending_top5": ["none", "none", "none", "none", "none"],
        }
    else:
        tasks = _extract_tasks_summary(tasks_md)

    email = _extract_email_signals(Path(args.gmail_reports))
    triage_age_hours: float | None = None
    triage_fresh: bool | None = None
    if email is None:
        reason_parts.append("email signal missing")
        emails_unread = urgent = invoices = 0
        email_subjects = ["none", "none"]
        triage_report_path = None
        triage_report_generated_at = None
    else:
        emails_unread = int(email.unread)
        urgent = int(email.urgent)
        invoices = int(email.invoices)
        email_subjects = (email.subjects_unread + ["none", "none"])[:2]
        triage_report_path = email.report_path
        triage_report_generated_at = email.report_generated_at

        threshold_hours = EMAIL_FRESHNESS_THRESHOLD_HOURS
        age_seconds = None
        if isinstance(triage_report_generated_at, str) and triage_report_generated_at.strip():
            try:
                gen_dt = datetime.fromisoformat(triage_report_generated_at)
                if gen_dt.tzinfo is None:
                    gen_dt = gen_dt.replace(tzinfo=tz)
                age_seconds = max(0.0, (now - gen_dt).total_seconds())
            except Exception:
                age_seconds = None
        if age_seconds is None and isinstance(email.report_mtime_epoch, (int, float)):
            age_seconds = max(0.0, now.timestamp() - float(email.report_mtime_epoch))
        if isinstance(age_seconds, (int, float)):
            triage_age_hours = float(age_seconds) / 3600.0
            triage_fresh = triage_age_hours <= threshold_hours
        if isinstance(triage_age_hours, (int, float)) and triage_age_hours > threshold_hours:
            reason_parts.append("email signal stale")

    errors_count = len(reason_parts)
    errors_flag = 0 if errors_count == 0 else 1
    status = "GREEN" if errors_flag == 0 else "YELLOW"
    error_reason = "" if errors_flag == 0 else ", ".join(reason_parts)[:60]
    reason = "ok" if errors_flag == 0 else error_reason
    icon = _status_icon(status)

    pending = tasks.get("pending_top5") or []
    pending = (list(pending) + ["none", "none", "none", "none", "none"])[:5]

    # Contract: 12-15 lines inclusive. We render 14 lines deterministically.
    lines = [
        f"{icon} EOD SUMMARY - {date_iso}",
        f"1) STATUS: {status} - {reason}",
        f"2) DONE: {int(tasks.get('done_count', 0))} completed",
        f"3) HIGHLIGHT: {tasks.get('highlight_done', 'none')}",
        "PENDING:",
        f"PENDING-1: {pending[0]}",
        f"PENDING-2: {pending[1]}",
        f"PENDING-3: {pending[2]}",
        f"PENDING-4: {pending[3]}",
        f"PENDING-5: {pending[4]}",
        f"EMAIL: {emails_unread} unread | {urgent} urgent | invoices: {invoices}",
        f"EMAIL-1: {email_subjects[0]}",
        f"EMAIL-2: {email_subjects[1]}",
    ]

    signal = {
        "product": "EOD_SUMMARY",
        "date": date_iso,
        "status": status,
        "emails": int(emails_unread),
        "urgent": int(urgent),
        "invoices": int(invoices),
        "errors": int(errors_flag),
    }
    s_short = _status_short(status)
    signal_token = (
        f"SIGNAL EOD|d={date_iso}|s={s_short}|e={int(emails_unread)}|u={int(urgent)}|"
        f"i={int(invoices)}|x={int(errors_flag)}"
    )
    lines.append(signal_token)

    if not (12 <= len(lines) <= 15) or not lines[-1].startswith("SIGNAL "):
        # Safe fallback (still within contract bounds)
        lines = [
            f"🔴 EOD SUMMARY - {date_iso}",
            "1) STATUS: RED - probe internal error",
            "2) DONE: 0 completed",
            "3) HIGHLIGHT: none",
            "PENDING:",
            "PENDING-1: none",
            "PENDING-2: none",
            "PENDING-3: none",
            "PENDING-4: none",
            "PENDING-5: none",
            "EMAIL: 0 unread | 0 urgent | invoices: 0",
            "EMAIL-1: none",
            "EMAIL-2: none",
            f"SIGNAL EOD|d={date_iso}|s=R|e=0|u=0|i=0|x=1",
        ]

    msg = "\n".join(lines)

    out_dir = Path(args.out_dir)
    signals_obj = {
        # Required schema keys (operator jq-friendly)
        "product": "EOD_SUMMARY",
        "date": date_iso,
        "status": status,
        "emails": int(emails_unread),
        "urgent": int(urgent),
        "invoices": int(invoices),
        "errors": int(errors_flag),
        "error_reason": error_reason,
        "error_count": int(errors_count),
        # Additional structured fields
        "done_count": int(tasks.get("done_count", 0)),
        "open_count": int(tasks.get("open_count", 0)),
        "highlight_done": tasks.get("highlight_done", "none"),
        "pending_top5": pending,
        "email_subjects_top2": email_subjects,
        "triage_report_age_hours": triage_age_hours,
        "triage_fresh": triage_fresh,
        "sources": {
            "tasks_path": str(args.tasks),
            "gmail_reports_dir": str(args.gmail_reports),
            "triage_report": triage_report_path,
            "triage_report_generated_at": triage_report_generated_at,
            "triage_report_age_hours": triage_age_hours,
            "email_freshness_threshold_hours": EMAIL_FRESHNESS_THRESHOLD_HOURS,
        },
        "signal_token": signal_token,
    }

    try:
        _atomic_write_json(out_dir / "signals.json", signals_obj)
        _atomic_write_text(out_dir / "message.txt", msg + "\n")
    except Exception:
        pass

    sys.stdout.write(msg)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
