#!/usr/bin/env python3
"""
PRD v13.0 - Newsletter Weekly probe + renderer (deterministic, local-first).

Input (read-only):
- /home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports/newsletter-weekly-*.json
  Produced by systemd: clawdbot-newsletter-master.service -> scripts/gmail_triage_poll.py --mode newsletter-weekly

Outputs (written to --out-dir; typically a per-run archive directory):
- report.json            Machine-readable full report with items[] and top3[]
- report.md              Hebrew human report (for Drive publishing)
- drive_doc.json         Written by drive publisher (not by this probe)
- telegram_message.txt   Final Telegram payload (exactly 6 lines)
- signals.json           Structured status for validators/ops

Telegram contract (exactly 6 lines):
1) <ICON> NEWSLETTER - YYYY-MM-DD
2) TOP-1: <headline>
3) TOP-2: <headline>
4) TOP-3: <headline>
5) דוח מלא: <Google Doc URL>
6) SIGNAL NW|d=YYYY-MM-DD|s=G|n=3|t=<n_items>|u=<n_unread>|x=<errors>

Notes:
- This probe does not call external services.
- If a Drive URL is not available yet, it is set to "none" and validation should FAIL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo


DEFAULT_TZ = "Asia/Jerusalem"
LOOKBACK_DAYS = 10

DEFAULT_REPORTS_DIR = Path("/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/reports")
DEFAULT_ALLOWLIST = Path("/home/rotemgrosman/jarvis-stack/jarvis-data/newsletters_allowlist.json")
DEFAULT_TAG_MAP = Path("/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/config/tag_map.json")
DEFAULT_CONFIG = Path("/home/rotemgrosman/jarvis-stack/jarvis-data/newsletter-weekly/config.json")


def _atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, mode)
    except PermissionError:
        pass
    os.replace(tmp, path)


def _atomic_write_json(path: Path, obj: Any, *, mode: int = 0o600) -> None:
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n", mode=mode)


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sanitize(s: str, *, max_len: int) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ").replace("<", "").replace(">", "").strip()
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


def _find_latest_report(reports_dir: Path, now: datetime) -> Path | None:
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    best: Tuple[datetime, Path] | None = None
    for p in reports_dir.glob("newsletter-weekly-*.json"):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=now.tzinfo)
        except Exception:
            continue
        if mtime < cutoff:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, p)
    return best[1] if best else None


def _parse_iso_dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


@dataclass(frozen=True)
class CanonTags:
    domain: str
    type: str
    priority: str
    source: str
    labels: List[str]


def _load_tag_map(path: Path) -> Dict[str, Any]:
    data = _read_json(path)
    return data if isinstance(data, dict) else {}


def _canon_tags(tag_map: Dict[str, Any], *, newsletter_label: str | None) -> CanonTags:
    defaults = tag_map.get("source_defaults") if isinstance(tag_map.get("source_defaults"), dict) else {}
    by_label = tag_map.get("by_newsletter_label") if isinstance(tag_map.get("by_newsletter_label"), dict) else {}
    chosen = by_label.get(newsletter_label) if isinstance(newsletter_label, str) else None
    chosen = chosen if isinstance(chosen, dict) else {}

    def _pick(key: str, fallback: str) -> str:
        v = chosen.get(key, defaults.get(key, fallback))
        return str(v) if isinstance(v, str) and v.strip() else fallback

    labels_raw = chosen.get("labels", defaults.get("labels", []))
    labels = [str(x).strip() for x in labels_raw] if isinstance(labels_raw, list) else []
    labels = [x for x in labels if x][:6]

    return CanonTags(
        domain=_pick("domain", "misc"),
        type=_pick("type", "newsletter"),
        priority=_pick("priority", "P3"),
        source=_pick("source", "gmail"),
        labels=labels,
    )


def _category_for(subject: str) -> str:
    s = (subject or "").lower()
    if any(k in s for k in ("security", "suspicious", "password", "2fa", "verify", "verification", "login", "recover", "אבטחה", "סיסמה", "קוד")):
        return "security"
    if any(k in s for k in ("invoice", "receipt", "bill", "charge", "payment", "paid", "חשבונית", "קבלה", "חיוב", "תשלום")):
        return "finance"
    if any(k in s for k in ("token", "credential", "reset", "api key", "גישה", "איפוס")):
        return "admin"
    return "other"


def _rank_weight(category: str) -> int:
    # Lower is better (selected first).
    return {"security": 0, "finance": 1, "admin": 2, "other": 3}.get(category, 3)


def _extract_item_id(thread_id: str, subject: str) -> str:
    tid = (thread_id or "").strip()
    if tid:
        return tid
    m = re.search(r"\b(\d{4,})\b", subject or "")
    return m.group(1) if m else "none"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tz", default=DEFAULT_TZ)
    ap.add_argument("--reports-dir", default=str(DEFAULT_REPORTS_DIR))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--tag-map", default=str(DEFAULT_TAG_MAP))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--min-items", type=int, default=10)
    ap.add_argument("--max-items", type=int, default=15)
    args = ap.parse_args()

    tz = ZoneInfo(str(args.tz))
    now = datetime.now(tz=tz)
    date_iso = now.date().isoformat()
    week_id = now.strftime("%G-W%V")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = _read_json(Path(args.config))
    cfg = cfg if isinstance(cfg, dict) else {}
    report_url = str(cfg.get("report_url") or "").strip() or "none"

    errors: List[str] = []
    reasons: List[str] = []

    upstream_path = _find_latest_report(Path(args.reports_dir), now)
    upstream = _read_json(upstream_path) if upstream_path else None
    if not upstream_path or not isinstance(upstream, dict):
        errors.append("missing_upstream_report")
        reasons.append("missing upstream report")
        upstream = {}

    upstream_items = upstream.get("items") if isinstance(upstream.get("items"), list) else []
    upstream_items = [x for x in upstream_items if isinstance(x, dict)]
    matched_n = upstream.get("matched")
    n_unread = int(matched_n) if isinstance(matched_n, int) else 0

    tag_map = _load_tag_map(Path(args.tag_map))
    canon_items: List[Dict[str, Any]] = []
    for it in upstream_items:
        subject = _sanitize(str(it.get("subject") or ""), max_len=160)
        if subject == "none":
            continue
        ms = it.get("matched_source") if isinstance(it.get("matched_source"), dict) else {}
        newsletter_label = ms.get("label") if isinstance(ms.get("label"), str) else None
        tags = _canon_tags(tag_map, newsletter_label=newsletter_label)
        thread_id = str(it.get("thread_id") or it.get("threadId") or it.get("id") or "").strip()
        item_id = _extract_item_id(thread_id, subject)
        category = _category_for(subject)

        dt_s = str(it.get("date") or "")
        dt_parsed = _parse_iso_dt(dt_s) if dt_s else None
        ts = int(dt_parsed.timestamp()) if dt_parsed else 0

        canon_items.append(
            {
                "title": subject,
                "source": _sanitize(str(ms.get("source") or it.get("from") or "gmail"), max_len=60),
                "url": _sanitize(str(it.get("gmail_url") or it.get("url") or ""), max_len=240),
                "thread_id": thread_id or "none",
                "published_at": dt_s or "none",
                "published_ts": ts,
                "tags": {
                    "domain": tags.domain,
                    "type": tags.type,
                    "priority": tags.priority,
                    "source": tags.source,
                    "labels": list(tags.labels),
                },
                "category": category,
                "id": item_id,
            }
        )

    # Sort deterministically by category ranking, then recency, then title.
    canon_items.sort(key=lambda x: (_rank_weight(str(x.get("category"))), -int(x.get("published_ts") or 0), str(x.get("title") or "").lower()))

    min_items = int(args.min_items)
    max_items = int(args.max_items)

    if len(canon_items) < min_items:
        errors.append("insufficient_items")
        reasons.append(f"items<{min_items}")

        # Canon contract requires 10-15 items even on empty upstream.
        # Pad deterministically with placeholders (ids must not be "none" for validator).
        d_tags = _canon_tags(tag_map, newsletter_label=None)
        tags_obj = {
            "domain": d_tags.domain,
            "type": d_tags.type,
            "priority": d_tags.priority,
            "source": d_tags.source,
            "labels": list(d_tags.labels),
        }
        for idx in range(len(canon_items) + 1, min_items + 1):
            canon_items.append(
                {
                    "title": "none",
                    "source": "none",
                    "url": "none",
                    "thread_id": "none",
                    "published_at": "none",
                    "published_ts": 0,
                    "tags": tags_obj,
                    "category": "other",
                    "id": f"placeholder-{idx:02d}",
                }
            )

    # Keep only max_items in the full report (deterministic).
    canon_items = canon_items[:max_items]

    top3 = canon_items[:3]
    if len(top3) < 3:
        errors.append("insufficient_top3")
        reasons.append("top3<3")
    while len(top3) < 3:
        idx = len(top3) + 1
        top3.append(
            {
                "title": "none",
                "source": "none",
                "url": "none",
                "thread_id": "none",
                "published_at": "none",
                "published_ts": 0,
                "tags": {"domain": "misc", "type": "newsletter", "priority": "P3", "source": "gmail", "labels": []},
                "category": "other",
                "id": f"placeholder-top{idx}",
            }
        )

    # Apply TOP tags.
    for idx, it in enumerate(top3, start=1):
        it["top_tag"] = f"TOP-{idx}"

    if report_url == "none":
        errors.append("missing_report_url")
        reasons.append("missing report url")

    status = "GREEN"
    if errors:
        status = "RED" if any(e in errors for e in ("missing_upstream_report", "insufficient_items", "insufficient_top3")) else "YELLOW"

    reason = _sanitize(", ".join(reasons) if reasons else "ok", max_len=60)
    x_errors = int(len(errors))

    signal = f"SIGNAL NW|d={date_iso}|s={_status_short(status)}|n=3|t={len(canon_items)}|u={n_unread}|x={x_errors}"

    icon = _status_icon(status)
    line1 = f"{icon} NEWSLETTER - {date_iso}"
    t1 = _sanitize(str(top3[0].get("title") or "none"), max_len=90)
    t2 = _sanitize(str(top3[1].get("title") or "none"), max_len=90)
    t3 = _sanitize(str(top3[2].get("title") or "none"), max_len=90)
    msg_lines = [
        line1,
        f"TOP-1: {t1}",
        f"TOP-2: {t2}",
        f"TOP-3: {t3}",
        f"דוח מלא: {report_url}",
        signal,
    ]
    telegram_message = "\n".join(msg_lines) + "\n"

    # Hebrew report.md (Drive content source).
    md_lines: List[str] = []
    md_lines.append(f"# ניוזלטר שבועי - {date_iso} (שבוע {week_id.split('-W')[-1]})")
    md_lines.append("")
    md_lines.append("## כותרות מובילות (TOP-3)")
    for it in top3:
        md_lines.append(f"- {it.get('title','none')}")
    md_lines.append("")
    md_lines.append("## כל הפריטים (10–15)")
    for it in canon_items:
        md_lines.append(f"- {it.get('title','none')}")
        md_lines.append(f"  - מקור: {it.get('source','none')}")
        md_lines.append(f"  - קטגוריה: {it.get('category','other')}")
        md_lines.append(f"  - תגיות: {it.get('tags',{}).get('domain','misc')}/{it.get('tags',{}).get('priority','P3')}")
        if str(it.get("url") or "none") != "none":
            md_lines.append(f"  - קישור: {it.get('url')}")
    md_lines.append("")
    md_lines.append("## מטא-דאטה")
    md_lines.append(f"- generated_at: {now.isoformat()}")
    md_lines.append(f"- upstream_report: {str(upstream_path) if upstream_path else 'none'}")
    md_lines.append(f"- items_count: {len(canon_items)}")
    md_lines.append(f"- errors: {', '.join(errors) if errors else 'none'}")
    report_md = "\n".join(md_lines).rstrip() + "\n"

    report_obj = {
        "product": "NEWSLETTER_WEEKLY",
        "generated_at": now.isoformat(),
        "date": date_iso,
        "week_id": week_id,
        "upstream_report": str(upstream_path) if upstream_path else "none",
        "report_url": report_url,
        "items": canon_items,
        "top3": top3,
        "errors": errors,
    }

    signals_obj = {
        "product": "NEWSLETTER_WEEKLY",
        "date": date_iso,
        "status": status,
        "errors": x_errors,
        "error_reason": "" if not errors else reason,
        "emails": int(n_unread),
        "urgent": 0,
        "invoices": 0,
        "sources": {
            "upstream_report": str(upstream_path) if upstream_path else "none",
            "tag_map": str(Path(args.tag_map)),
            "report_url": report_url,
        },
    }

    _atomic_write_json(out_dir / "report.json", report_obj, mode=0o600)
    _atomic_write_text(out_dir / "report.md", report_md, mode=0o600)
    _atomic_write_json(out_dir / "signals.json", signals_obj, mode=0o600)
    _atomic_write_text(out_dir / "telegram_message.txt", telegram_message, mode=0o600)
    _atomic_write_text(out_dir / "summary.txt", f"status={status}\nreason={reason}\n", mode=0o600)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
