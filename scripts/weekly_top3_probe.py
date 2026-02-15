#!/usr/bin/env python3
"""
Deterministic Weekly Top-3 Headlines probe + renderer (PRD v11.0).

Derives items from local gmail-triage artifacts (no direct Gmail reads):
  - /home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports/gmail-triage-*.json

Writes canonical artifacts:
  - /home/rotemgrosman/jarvis-stack/jarvis-data/weekly-top3/message.txt
  - /home/rotemgrosman/jarvis-stack/jarvis-data/weekly-top3/signals.json
  - /home/rotemgrosman/jarvis-stack/jarvis-data/weekly-top3/report.json (items[])

Telegram contract (exactly 6 lines):
1) <ICON> WEEKLY TOP 3 - YYYY-MM-DD
2) TOP-1: <title> (<source>)
3) TOP-2: <title> (<source>)
4) TOP-3: <title> (<source>)
5) REPORT: <stable local path>
6) SIGNAL W|d=YYYY-MM-DD|s=G|n=3|x=0
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_TZ = "Asia/Jerusalem"
LOOKBACK_DAYS = 7

DEFAULT_GMAIL_REPORTS_DIR = Path(
    "/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports"
)
DEFAULT_OUT_DIR = Path("/home/rotemgrosman/jarvis-stack/jarvis-data/weekly-top3")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_json(path: Path, obj: Any) -> None:
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sanitize_token(value: str, *, max_len: int = 120) -> str:
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


@dataclass(frozen=True)
class Item:
    title: str
    source: str
    url: str
    published_at: str | None
    score: int
    report_path: str
    thread_id: str | None


def _score_item(subject: str, from_field: str, labels: list[str]) -> int:
    s = subject.lower()
    f = from_field.lower()
    score = 0
    if "unread" in [x.lower() for x in labels]:
        score += 2
    if any(k in s for k in ("invoice", "receipt", "bill", "חשבונית", "קבלה")):
        score += 5
    if any(k in s for k in ("urgent", "asap", "דחוף")):
        score += 4
    if "google" in f or "stripe" in f or "openai" in f:
        score += 1
    return score


def _gather_items(reports_dir: Path, now: datetime) -> list[Item]:
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    items: list[Item] = []
    seen: set[str] = set()

    for path in sorted(reports_dir.glob("gmail-triage-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=now.tzinfo)
        except Exception:
            continue
        if mtime < cutoff:
            continue
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        new_threads = data.get("new_threads") if isinstance(data.get("new_threads"), list) else []
        for t in new_threads:
            if not isinstance(t, dict):
                continue
            tid = t.get("id")
            subject = t.get("subject")
            from_field = t.get("from")
            labels = t.get("labels") if isinstance(t.get("labels"), list) else []
            if not isinstance(subject, str) or not subject.strip():
                continue
            key = str(tid) if tid else subject.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            src = str(from_field) if isinstance(from_field, str) and from_field.strip() else "none"
            src = _sanitize_token(src, max_len=40)
            title = _sanitize_token(subject, max_len=120)
            url = (
                f"https://mail.google.com/mail/u/0/#inbox/{tid}"
                if isinstance(tid, str) and tid.strip()
                else "none"
            )
            score = _score_item(subject, src, [str(x) for x in labels])
            items.append(
                Item(
                    title=title,
                    source=src,
                    url=url,
                    published_at=None,
                    score=int(score),
                    report_path=str(path),
                    thread_id=str(tid) if isinstance(tid, str) else None,
                )
            )

    # Deterministic ordering: score desc, then title asc, then source asc.
    items.sort(key=lambda it: (-it.score, it.title.lower(), it.source.lower()))
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tz", default=DEFAULT_TZ)
    ap.add_argument("--gmail-reports", default=str(DEFAULT_GMAIL_REPORTS_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()

    tz = ZoneInfo(str(args.tz))
    now = datetime.now(tz=tz)
    date_iso = now.date().isoformat()

    items = _gather_items(Path(args.gmail_reports), now)

    # Select top 3 (deterministic). If insufficient, fill with "none" lines and mark YELLOW.
    selected = items[:3]
    reason_parts: list[str] = []
    if len(selected) < 3:
        reason_parts.append("insufficient items")
    errors_flag = 0 if len(reason_parts) == 0 else 1
    status = "GREEN" if errors_flag == 0 else "YELLOW"
    error_reason = "" if errors_flag == 0 else ", ".join(reason_parts)[:60]

    # Build report.json items[] (machine-readable).
    report_path = str(Path(args.out_dir) / "report.json")
    items_obj = []
    for idx, it in enumerate(selected, start=1):
        items_obj.append(
            {
                "rank": idx,
                "selected": True,
                "title": it.title,
                "source": it.source,
                "url": it.url,
                "published_at": it.published_at,
                "score": int(it.score),
                "thread_id": it.thread_id,
                "source_report": it.report_path,
            }
        )
    # If fewer than 3, pad deterministically.
    for idx in range(len(items_obj) + 1, 4):
        items_obj.append(
            {
                "rank": idx,
                "selected": True,
                "title": "none",
                "source": "none",
                "url": "none",
                "published_at": None,
                "score": 0,
                "thread_id": None,
                "source_report": None,
            }
        )

    out_dir = Path(args.out_dir)
    report_obj = {
        "product": "WEEKLY_TOP3",
        "date": date_iso,
        "generated_at": now.isoformat(),
        "items": items_obj,
        "sources": {
            "gmail_reports_dir": str(args.gmail_reports),
            "lookback_days": LOOKBACK_DAYS,
        },
    }
    _atomic_write_json(out_dir / "report.json", report_obj)

    icon = _status_icon(status)
    s_short = _status_short(status)
    signal_token = f"SIGNAL W|d={date_iso}|s={s_short}|n=3|x={int(errors_flag)}"

    # Exactly 6 lines.
    def line_for(n: int) -> str:
        it = items_obj[n - 1]
        return f"TOP-{n}: {it['title']} ({it['source']})"

    msg_lines = [
        f"{icon} WEEKLY TOP 3 - {date_iso}",
        line_for(1),
        line_for(2),
        line_for(3),
        f"REPORT: {report_path}",
        signal_token,
    ]

    msg = "\n".join(msg_lines)

    signals_obj = {
        "product": "WEEKLY_TOP3",
        "date": date_iso,
        "status": status,
        "emails": 0,
        "urgent": 0,
        "invoices": 0,
        "errors": int(errors_flag),
        "error_reason": error_reason,
        "sources": {
            "gmail_reports_dir": str(args.gmail_reports),
            "report": report_path,
        },
        "signal_token": signal_token,
    }
    _atomic_write_json(out_dir / "signals.json", signals_obj)
    _atomic_write_text(out_dir / "message.txt", msg + "\n")

    sys.stdout.write(msg)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
