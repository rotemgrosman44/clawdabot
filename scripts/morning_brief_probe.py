#!/usr/bin/env python3
"""
Deterministic Morning Brief signal probe + renderer (PRD v11.0).

Reads (local, read-only):
  - /home/rotemgrosman/second-brain/tasks/today.md
  - /home/rotemgrosman/second-brain/projects/workflow.md
  - /home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports/*.json

Writes (local):
  - /home/rotemgrosman/jarvis-stack/jarvis-data/morning-brief/signals.json
  - /home/rotemgrosman/jarvis-stack/jarvis-data/morning-brief/message.txt

Prints the final Telegram body (exactly 8 lines) to stdout.
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
DEFAULT_WORKFLOW_PATH = Path("/home/rotemgrosman/second-brain/projects/workflow.md")
DEFAULT_GMAIL_REPORTS_DIR = Path(
    "/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports"
)
DEFAULT_OUT_DIR = Path("/home/rotemgrosman/jarvis-stack/jarvis-data/morning-brief")


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
    # Keep the output contract separators intact and avoid multiline output.
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


def _slice_h2_section(lines: list[str], title_regex: re.Pattern[str]) -> list[str] | None:
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*##\s+", line) and title_regex.search(line):
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^\s*##\s+", lines[j]):
            end = j
            break
    return lines[start:end]


def _extract_first_unchecked_task(section_lines: list[str]) -> tuple[str, str | None]:
    """
    Returns: (task_title, next_action?) where next_action is pulled from an adjacent
    'Next:' line if present.
    """
    task_idx = None
    title = None
    for i, line in enumerate(section_lines):
        m = re.match(r"^\s*-\s*\[\s*\]\s+(.*)$", line)
        if m:
            task_idx = i
            title = m.group(1).strip()
            break
    if task_idx is None or title is None:
        return ("none", None)

    next_action = None
    # Look ahead a handful of lines for an indented "- Next:" style attribute.
    for j in range(task_idx + 1, min(task_idx + 12, len(section_lines))):
        m = re.match(r"^\s*-\s*Next:\s*(.*)$", section_lines[j])
        if m:
            next_action = m.group(1).strip()
            break
    return (_sanitize_token(title, max_len=90), _sanitize_token(next_action, max_len=90) if next_action else None)


def _count_open_il_index_tasks(md: str) -> int:
    count = 0
    for line in md.splitlines():
        if re.search(r"\bIL-INDEX\b", line, flags=re.IGNORECASE) and re.search(
            r"^\s*-\s*\[\s*\]\s+", line
        ):
            count += 1
    return count


def _extract_tasks_tokens(md: str) -> tuple[str, str, str, str | None]:
    lines = md.splitlines()
    urgent_section = _slice_h2_section(lines, re.compile(r"\burgent\b", re.IGNORECASE))
    important_section = _slice_h2_section(
        lines, re.compile(r"\bimportant\b", re.IGNORECASE)
    )
    nice_section = _slice_h2_section(
        lines, re.compile(r"\bnice\b|nice to have|optional", re.IGNORECASE)
    )

    urgent, urgent_next = (
        _extract_first_unchecked_task(urgent_section) if urgent_section else ("none", None)
    )
    important, _ = (
        _extract_first_unchecked_task(important_section)
        if important_section
        else ("none", None)
    )
    nice, _ = (
        _extract_first_unchecked_task(nice_section) if nice_section else ("none", None)
    )
    return urgent, important, nice, urgent_next


@dataclass(frozen=True)
class EmailSignals:
    unread: int
    urgent: int
    invoices: int
    report_path: str | None
    report_generated_at: str | None
    report_mtime_epoch: float | None


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
    for t in new_threads:
        if not isinstance(t, dict):
            continue
        labels = t.get("labels")
        if isinstance(labels, list) and any(str(x) == "UNREAD" for x in labels):
            unread_threads += 1

    urgent = _coerce_int(summary.get("urgent"))
    invoices = _coerce_int(summary.get("invoices"))
    generated_at = data.get("generated_at")
    generated_at_str = str(generated_at) if isinstance(generated_at, str) else None

    return EmailSignals(
        unread=int(unread_threads),
        urgent=int(urgent),
        invoices=int(invoices),
        report_path=str(triage_report),
        report_generated_at=generated_at_str,
        report_mtime_epoch=mtime,
    )


def _extract_newsletter_token(reports_dir: Path) -> tuple[str, str | None]:
    report = _pick_latest_report(reports_dir, "newsletter-weekly-*.json")
    if not report:
        return ("none", None)
    data = _read_json(report)
    if not isinstance(data, dict):
        return ("none", str(report))
    errors = data.get("errors")
    err_count = len(errors) if isinstance(errors, list) else 0
    # Avoid placeholder-like tokens (v11.0); keep deterministic.
    token = "ok" if err_count == 0 else "none"
    return (token, str(report))


def _extract_workflow_tokens(md: str) -> tuple[str, str]:
    lines = md.splitlines()
    # Restrict parsing to the "Current Active Leads" section to avoid noise.
    section = _slice_h2_section(
        lines, re.compile(r"current active leads", re.IGNORECASE)
    )
    if not section:
        return ("none", "none")

    leads: list[tuple[str, str]] = []
    i = 0
    while i < len(section):
        m = re.match(r"^\s*####\s+\d+\.\s+(.*)$", section[i])
        if not m:
            i += 1
            continue
        lead_name = m.group(1).strip()
        status = None
        j = i + 1
        while j < len(section) and not re.match(r"^\s*####\s+\d+\.\s+", section[j]):
            ms = re.match(r"^\s*-\s+\*\*Status:\*\*\s*(.*)$", section[j])
            if ms and status is None:
                status = ms.group(1).strip()
                break
            j += 1
        status = status or "none"

        def short_key(name: str) -> str:
            if re.search(r"\bBP\b", name):
                return "BP"
            if re.search(r"kaplan|קפלן", name, flags=re.IGNORECASE):
                return "Kaplan"
            if re.search(r"memo", name, flags=re.IGNORECASE):
                return "Memo"
            # fallback: first token-ish chunk
            return name.split(" ")[0] if name.split(" ") else "Lead"

        leads.append((short_key(lead_name), status))
        i = j

    # WORKFLOW: short operational update on active leads (top 3).
    parts = [f"{k}: {_sanitize_token(v, max_len=60)}" for k, v in leads[:3]]
    workflow_token = _sanitize_token("; ".join(parts), max_len=120) if parts else "none"

    # BP token: status of the first BP lead found.
    bp_token = "none"
    for k, v in leads:
        if k == "BP":
            bp_token = _sanitize_token(v, max_len=40)
            break

    return (workflow_token, bp_token)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tz", default=DEFAULT_TZ)
    ap.add_argument("--tasks", default=str(DEFAULT_TASKS_PATH))
    ap.add_argument("--workflow", default=str(DEFAULT_WORKFLOW_PATH))
    ap.add_argument("--gmail-reports", default=str(DEFAULT_GMAIL_REPORTS_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()

    tz = ZoneInfo(str(args.tz))
    now = datetime.now(tz=tz)
    date_iso = now.date().isoformat()

    reason_parts: list[str] = []
    triage_age_hours: float | None = None
    triage_fresh: bool | None = None

    tasks_md = _read_text(Path(args.tasks))
    if tasks_md is None:
        reason_parts.append("tasks missing")
        urgent_task = important_task = nice_task = "none"
        urgent_next = None
        il_index_token = "stable"
    else:
        urgent_task, important_task, nice_task, urgent_next = _extract_tasks_tokens(tasks_md)
        il_open = _count_open_il_index_tasks(tasks_md)
        il_index_token = "change" if il_open > 0 else "stable"

    workflow_md = _read_text(Path(args.workflow))
    if workflow_md is None:
        reason_parts.append("workflow missing")
        workflow_token = "none"
        bp_token = "none"
    else:
        workflow_token, bp_token = _extract_workflow_tokens(workflow_md)

    email = _extract_email_signals(Path(args.gmail_reports))
    if email is None:
        reason_parts.append("email signal missing")
        emails_unread = urgent = invoices = 0
        email_report_path = None
        email_report_generated_at = None
    else:
        emails_unread = int(email.unread)
        urgent = int(email.urgent)
        invoices = int(email.invoices)
        email_report_path = email.report_path
        email_report_generated_at = email.report_generated_at

        # Mark stale if the last triage artifact is old (local-only check).
        threshold_hours = EMAIL_FRESHNESS_THRESHOLD_HOURS
        age_seconds = None
        if isinstance(email_report_generated_at, str) and email_report_generated_at.strip():
            try:
                gen_dt = datetime.fromisoformat(email_report_generated_at)
                if gen_dt.tzinfo is None:
                    gen_dt = gen_dt.replace(tzinfo=tz)
                age_seconds = max(0.0, (now - gen_dt).total_seconds())
            except Exception:
                age_seconds = None
        if age_seconds is None and isinstance(email.report_mtime_epoch, (int, float)):
            age_seconds = max(0.0, now.timestamp() - float(email.report_mtime_epoch))
        if isinstance(age_seconds, (int, float)):
            triage_age_hours = float(age_seconds) / 3600.0
        if isinstance(triage_age_hours, (int, float)):
            triage_fresh = triage_age_hours <= threshold_hours
        if isinstance(triage_age_hours, (int, float)) and triage_age_hours > threshold_hours:
            reason_parts.append("email signal stale")

    newsletter_token, newsletter_report_path = _extract_newsletter_token(
        Path(args.gmail_reports)
    )

    errors_count = len(reason_parts)
    errors_flag = 0 if errors_count == 0 else 1
    status = "GREEN" if errors_flag == 0 else "YELLOW"
    error_reason = "" if errors_flag == 0 else ", ".join(reason_parts)[:60]
    reason = "ok" if errors_flag == 0 else error_reason

    idea = "none"
    if urgent_next and urgent_next != "none":
        idea = urgent_next

    icon = _status_icon(status)

    # Build the frozen 8-line contract output (v10.4).
    lines = [
        f"{icon} MORNING BRIEF - {date_iso}",
        f"1) STATUS: {status} - {reason}",
        f"2) EMAIL: {emails_unread} unread | {urgent} urgent | invoices: {invoices}",
        f"3) TASKS: urgent={urgent_task} | important={important_task} | nice={nice_task}",
        f"4) WORKFLOW: {workflow_token}",
        f"5) CONTEXT: IL-INDEX={il_index_token} | BP={bp_token} | Newsletter={newsletter_token}",
        f"6) IDEA: {idea}",
    ]
    signal = {
        "product": "MORNING_BRIEF",
        "date": date_iso,
        "status": status,
        "emails": int(emails_unread),
        "urgent": int(urgent),
        "invoices": int(invoices),
        "errors": int(errors_flag),
    }
    # Tokenized SIGNAL line (Telegram-safe, deterministic).
    s_short = _status_short(status)
    signal_token = (
        f"SIGNAL MB|d={date_iso}|s={s_short}|e={int(emails_unread)}|u={int(urgent)}|"
        f"i={int(invoices)}|x={int(errors_flag)}"
    )
    lines.append(signal_token)

    # Final safety: enforce exact 8 lines and no placeholders.
    if len(lines) != 8:
        # This should never happen; force a safe fallback.
        lines = [
            f"🔴 MORNING BRIEF - {date_iso}",
            "1) STATUS: RED - probe internal error",
            "2) EMAIL: 0 unread | 0 urgent | invoices: 0",
            "3) TASKS: urgent=none | important=none | nice=none",
            "4) WORKFLOW: none",
            "5) CONTEXT: IL-INDEX=stable | BP=none | Newsletter=unknown",
            "6) IDEA: none",
            f"SIGNAL MB|d={date_iso}|s=R|e=0|u=0|i=0|x=1",
        ]

    msg = "\n".join(lines)

    out_dir = Path(args.out_dir)
    signals_obj = {
        # Required schema keys (operator jq-friendly)
        "product": "MORNING_BRIEF",
        "date": date_iso,
        "status": status,
        "emails": int(emails_unread),
        "urgent": int(urgent),
        "emails_unread": int(emails_unread),
        "emails_urgent": int(urgent),
        "invoices": int(invoices),
        "tasks": {
            "urgent": urgent_task,
            "important": important_task,
            "nice": nice_task,
        },
        "workflow": workflow_token,
        "context": {
            "il_index": il_index_token,
            "bp": bp_token,
            "newsletter": newsletter_token,
        },
        "errors": int(errors_flag),
        "error_reason": error_reason,
        "error_count": int(errors_count),
        "triage_report_age_hours": triage_age_hours,
        "triage_fresh": triage_fresh,
        "sources": {
            "tasks_path": str(args.tasks),
            "workflow_path": str(args.workflow),
            "gmail_reports_dir": str(args.gmail_reports),
            "triage_report": email_report_path,
            "triage_report_generated_at": email_report_generated_at,
            "triage_report_age_hours": triage_age_hours,
            "newsletter_report": newsletter_report_path,
            "email_freshness_threshold_hours": EMAIL_FRESHNESS_THRESHOLD_HOURS,
        },
        "signal_token": signal_token,
    }

    try:
        _atomic_write_json(out_dir / "signals.json", signals_obj)
        _atomic_write_text(out_dir / "message.txt", msg + "\n")
    except Exception:
        # Do not fail the cron run due to local writes; stdout is the contract.
        pass

    sys.stdout.write(msg)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
