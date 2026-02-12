#!/usr/bin/env python3
"""
Polling-based Gmail triage and newsletter runner for the Jarvis stack.

Safety goals:
- No permanent delete operations.
- Gmail write actions are deterministic and configurable.
- Every action is auditable (report file + structured log line).
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


DEFAULT_MAX_THREADS = 20
DEFAULT_WORD_LIMIT = 280
DEFAULT_OVERLAP_SECONDS = 10 * 60
DEFAULT_INITIAL_WINDOW_SECONDS = 3 * 60 * 60
DEFAULT_NEWSLETTER_LOOKBACK_DAYS = 7
DEFAULT_MAX_ACTIONS = 120

PERSONAL_DOMAINS = {
    "gmail.com",
    "icloud.com",
    "me.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "proton.me",
    "protonmail.com",
    "walla.co.il",
    "yandex.com",
}

SPAM_KEYWORDS = [
    "free money",
    "act now",
    "guaranteed income",
    "forex",
    "crypto",
    "bitcoin profit",
    "casino",
    "adult",
    "loan approved",
    "זכית",
    "מתנה",
    "הלוואה",
]

URGENT_KEYWORDS = ["urgent", "asap", "deadline", "action required", "דחוף", "מיידי"]
IMPORTANT_KEYWORDS = [
    "invoice",
    "receipt",
    "payment",
    "billing",
    "security",
    "github",
    "pull request",
    "חשבונית",
    "קבלה",
    "תשלום",
    "חיוב",
]

DEFAULT_CONFIG = {
    "version": 1,
    "scheduler": {
        "authority": "systemd",
        "disallowedEnabledCronJobs": ["gmail-plumber-daily", "newsletter-master-weekly"],
        "alertOnViolation": True,
    },
    "write": {
        "enabled": True,
        "policy": {
            "minAgeDays": 14,
            "allowedActions": ["label", "archive", "trash"],
        },
        "labels": {"enabled": True},
        "trash": {
            "enabled": True,
            "newsletters": {
                "enabled": True,
                "allowlistOnly": True,
                "cleanupNonAllowlistedAfterDays": DEFAULT_NEWSLETTER_LOOKBACK_DAYS,
                "cleanupCategories": ["CATEGORY_PROMOTIONS"],
            },
            "spam": {"enabled": True, "minConfidence": 0.95},
        },
    },
    "notifications": {
        "telegram": {
            "highSignalOnly": True,
            "maxExamplesPerPriority": 3,
            "quietDayMode": "heartbeat",
            "quietDayHeartbeatText": "אימייל: בדיקה יומית. נסרקו {scanned}. דחוף={urgent}. חשוב={important}. מידע={info}. ספאם={spam}.",
            "defaultLanguage": "he",
        }
    },
    "newsletter": {
        "lookbackDays": DEFAULT_NEWSLETTER_LOOKBACK_DAYS,
    },
    "safety": {
        "allowPermanentDelete": False,
    },
}

HEBREW_CHAR_RE = re.compile(r"[\u0590-\u05FF]")
LATIN_CHAR_RE = re.compile(r"[A-Za-z]")

SUBAGENT_TEMPLATES: Dict[str, Dict[str, str]] = {
    "gmail-plumber": {
        "title": "Gmail Plumber",
        "identity": """# Gmail Plumber\n\nMission: keep inbox operational by classifying threads, applying labels, and routing safe trash actions.\nScope: Gmail triage only.\nOwner: Jarvis CEO dispatcher.\n""",
        "policy": """# Policy\n\n1. No permanent deletion.\n2. Labeling is allowed automatically.\n3. Trash only when strict deterministic rule matched.\n4. Every write action must be logged and recorded.\n""",
    },
    "newsletter-master": {
        "title": "Newsletter Master",
        "identity": """# Newsletter Master\n\nMission: compile a weekly digest from approved newsletter sources and clean processed messages.\nScope: EverydayAI, FutureTools, The Rundown allowlist only.\nOwner: Jarvis CEO dispatcher.\n""",
        "policy": """# Policy\n\n1. Process only allowlisted sources.\n2. Generate report before trashing newsletter threads.\n3. No permanent deletion.\n4. Record source counts per run.\n""",
    },
    "invoices-gmail-agent": {
        "title": "Invoices Gmail Agent",
        "identity": """# Invoices Gmail Agent\n\nMission: extract invoice/receipt signals and build monthly summaries.\nStatus: phase-2 placeholder.\nOwner: Jarvis CEO dispatcher.\n""",
        "policy": """# Policy\n\n1. Read-only until explicit phase-2 activation.\n2. No write action outside invoice labels.\n""",
    },
    "il-index-growth-manager": {
        "title": "IL Index Growth Manager",
        "identity": """# IL Index Growth Manager\n\nMission: monitor IL-INDEX growth signals and suggest concrete actions.\nStatus: phase-3 placeholder.\nOwner: Jarvis CEO dispatcher.\n""",
        "policy": """# Policy\n\n1. Suggestion-only mode until explicit activation.\n2. No external write actions.\n""",
    },
}


@dataclass(frozen=True)
class ThreadRow:
    id: str
    date: str
    from_: str
    subject: str
    labels: List[str]
    message_count: int


@dataclass(frozen=True)
class MatchedSource:
    source: str
    label: str


@dataclass
class Action:
    kind: str
    thread_id: str
    add: List[str]
    remove: List[str]
    reason: str
    confidence: float = 1.0
    age_days: Optional[float] = None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone()


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _ensure_dir(path: Path, mode: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, mode)
    except PermissionError:
        pass


def _atomic_write_json(path: Path, data: Any, mode: int = 0o600) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(path)


def _json_log(level: str, event: str, **fields: Any) -> None:
    row = {
        "ts": _now().isoformat(),
        "level": level,
        "event": event,
        **fields,
    }
    print(json.dumps(row, ensure_ascii=False), flush=True)


def _run(cmd: Sequence[str], timeout_s: int, env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
    proc = subprocess.run(
        list(cmd),
        text=True,
        capture_output=True,
        timeout=timeout_s,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _extract_json_payload(raw: str) -> Optional[Any]:
    if not raw:
        return None
    start = raw.find("{")
    if start < 0:
        return None
    candidate = raw[start:].strip()
    try:
        return json.loads(candidate)
    except Exception:
        return None


def _require_env_keys(keys: List[str]) -> List[str]:
    return [k for k in keys if not os.environ.get(k)]


def _extract_email(from_field: str) -> str:
    m = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+)", from_field)
    return (m.group(1) if m else "").strip().lower()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default


def _parse_thread_date(value: str, tz: dt.tzinfo) -> Optional[dt.datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = dt.datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=tz)
        except ValueError:
            continue
    return None


def _compute_age_days(value: str, now_local: dt.datetime) -> Optional[float]:
    parsed = _parse_thread_date(value, now_local.tzinfo or dt.timezone.utc)
    if parsed is None:
        return None
    delta = now_local - parsed
    return max(delta.total_seconds(), 0.0) / 86400.0
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_source_slug(source: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", source).strip("-")
    return slug or "newsletter"


def _load_allowlist(path: Path) -> List[Dict[str, Any]]:
    raw = _load_json(path, {"version": 1, "allowlist": []})
    if not isinstance(raw, dict):
        return []
    entries = raw.get("allowlist")
    if not isinstance(entries, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or item.get("name") or "").strip()
        if not source:
            continue
        source_slug = _normalize_source_slug(source)
        label = str(item.get("label") or f"NEWSLETTER::{source}").strip()
        emails = item.get("emails") if isinstance(item.get("emails"), list) else [item.get("email")]
        domains = item.get("domains") if isinstance(item.get("domains"), list) else [item.get("domain")]
        patterns = item.get("patterns") if isinstance(item.get("patterns"), list) else [item.get("pattern")]
        normalized.append(
            {
                "source": source,
                "sourceSlug": source_slug,
                "label": label,
                "emails": [str(v).strip().lower() for v in emails if isinstance(v, str) and v.strip()],
                "domains": [str(v).strip().lower() for v in domains if isinstance(v, str) and v.strip()],
                "patterns": [str(v).strip() for v in patterns if isinstance(v, str) and v.strip()],
            }
        )
    return normalized


def _match_allowlist(from_field: str, subject: str, allowlist: List[Dict[str, Any]]) -> Optional[MatchedSource]:
    from_l = from_field.lower()
    subject_l = subject.lower()
    email = _extract_email(from_field)
    domain = email.split("@", 1)[1] if "@" in email else ""

    for entry in allowlist:
        source = str(entry.get("source") or "").strip()
        label = str(entry.get("label") or "").strip()
        if not source or not label:
            continue

        for candidate in entry.get("emails") or []:
            if email and email == candidate:
                return MatchedSource(source=source, label=label)

        for candidate in entry.get("domains") or []:
            if domain and domain == candidate:
                return MatchedSource(source=source, label=label)

        for pat in entry.get("patterns") or []:
            try:
                if re.search(pat, from_l) or re.search(pat, subject_l):
                    return MatchedSource(source=source, label=label)
            except re.error:
                continue

    return None


def _classify_priority(thread: ThreadRow) -> str:
    subject = thread.subject.lower()
    from_l = thread.from_.lower()

    if "SPAM" in thread.labels:
        return "SPAM"
    if any(kw in subject for kw in URGENT_KEYWORDS):
        return "URGENT"
    if any(kw in subject for kw in IMPORTANT_KEYWORDS):
        return "IMPORTANT"
    if "github.com" in from_l or "noreply@github.com" in from_l:
        return "IMPORTANT"
    return "INFO"


def _is_invoice(thread: ThreadRow) -> bool:
    subject = thread.subject.lower()
    return any(kw in subject for kw in ["invoice", "receipt", "חשבונית", "קבלה", "billing", "payment"])


def _spam_confidence(thread: ThreadRow) -> float:
    subject = thread.subject.lower()
    from_l = thread.from_.lower()
    score = 0.0

    if "SPAM" in thread.labels:
        score += 1.0

    for kw in SPAM_KEYWORDS:
        if kw in subject:
            score += 0.35
        if kw in from_l:
            score += 0.35

    suspicious_domains = [
        "mail.ru",
        "tempmail",
        "mailinator",
        "crypto",
        "forex",
    ]
    if any(d in from_l for d in suspicious_domains):
        score += 0.3

    return min(score, 1.0)


def _route_business_vs_personal(thread: ThreadRow) -> str:
    email = _extract_email(thread.from_)
    domain = email.split("@", 1)[1] if "@" in email else ""
    if domain in PERSONAL_DOMAINS:
        return "PERSONAL_THREAD"
    return "BUSINESS_THREAD"


def _normalize_category_label(raw: str) -> str:
    text = str(raw or "").strip().upper()
    if not text:
        return ""
    if text.startswith("CATEGORY_"):
        return text
    return f"CATEGORY_{text}"


def _is_newsletter_cleanup_candidate(thread: ThreadRow, cleanup_categories: Sequence[str]) -> bool:
    if not cleanup_categories:
        return False
    labels = {str(v).strip().upper() for v in (thread.labels or [])}
    wanted = {_normalize_category_label(v) for v in cleanup_categories if str(v).strip()}
    wanted.discard("")
    return bool(labels.intersection(wanted))


def _format_triage_digest(
    *,
    now_local: dt.datetime,
    summary: Dict[str, Any],
    grouped: Dict[str, List[ThreadRow]],
    word_limit: int,
    max_examples: int,
    write_stats: Dict[str, Any],
    scanned: int,
    language: str,
) -> str:
    lang = "en" if language == "en" else "he"
    urgent = int(summary.get("urgent", 0))
    important = int(summary.get("important", 0))
    info = int(summary.get("info", 0))
    spam = int(summary.get("spam", 0))

    if lang == "en":
        lines = [
            f"1. 📬 Daily Gmail triage ({now_local:%H:%M})",
            f"scanned={scanned}. urgent={urgent}. important={important}. info={info}. spam={spam}.",
            "",
            (
                "2. 🧹 Gmail writes: "
                f"label={write_stats.get('label_success', 0)}. "
                f"archive={write_stats.get('archive_success', 0)}. "
                f"trash={write_stats.get('trash_success', 0)}. "
                f"failed={write_stats.get('failed', 0)}."
            ),
            "",
            f"3. Examples (up to {max_examples} per priority):",
        ]
        priority_labels = [
            ("URGENT", "urgent"),
            ("IMPORTANT", "important"),
            ("INFO", "info"),
            ("SPAM", "spam"),
        ]
        empty_text = "No examples in this run."
    else:
        lines = [
            f"1. 📬 סיכום טריאז' אימייל ({now_local:%H:%M})",
            f"נסרקו={scanned}. דחוף={urgent}. חשוב={important}. מידע={info}. ספאם={spam}.",
            "",
            (
                "2. 🧹 פעולות Gmail: "
                f"תיוג={write_stats.get('label_success', 0)}. "
                f"ארכיון={write_stats.get('archive_success', 0)}. "
                f"אשפה={write_stats.get('trash_success', 0)}. "
                f"כשלים={write_stats.get('failed', 0)}."
            ),
            "",
            f"3. דוגמאות (עד {max_examples} לכל עדיפות):",
        ]
        priority_labels = [
            ("URGENT", "דחוף"),
            ("IMPORTANT", "חשוב"),
            ("INFO", "מידע"),
            ("SPAM", "ספאם"),
        ]
        empty_text = "אין דוגמאות במחזור הזה."

    has_examples = False
    for priority, label in priority_labels:
        items = grouped.get(priority) or []
        if not items:
            continue
        has_examples = True
        lines.append(f"- {label}:")
        for idx, t in enumerate(items[:max_examples], start=1):
            lines.append(f"{idx}. {t.subject.strip()[:110]}")

    if not has_examples:
        lines.append(empty_text)

    text = "\n".join(lines).strip() + "\n"
    if _word_count(text) > word_limit:
        words = text.split()
        text = " ".join(words[:word_limit]) + "\n"
    return text


def _format_newsletter_digest_md(now_local: dt.datetime, items: List[Tuple[ThreadRow, MatchedSource]]) -> str:
    by_source: Dict[str, List[ThreadRow]] = {}
    for thread, source in items:
        by_source.setdefault(source.source, []).append(thread)

    lines = [
        f"# Newsletter Digest ({now_local:%Y-%m-%d})",
        "",
        "## Sources",
    ]
    for source_name in sorted(by_source.keys()):
        lines.append(f"- {source_name}: {len(by_source[source_name])}")

    lines.append("")
    lines.append("## Items")

    for source_name in sorted(by_source.keys()):
        lines.append("")
        lines.append(f"### {source_name}")
        threads = by_source[source_name]
        for thread in threads:
            lines.append(f"- {thread.date} | {thread.subject.strip()[:140]}")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Policy: allowlist-only newsletters. Permanent delete disabled.")
    lines.append("")
    return "\n".join(lines)


def _gog_search_threads(gog: str, account: str, query: str, max_threads: int) -> Tuple[bool, List[ThreadRow], bool, str]:
    cmd = [
        gog,
        "gmail",
        "search",
        "--account",
        account,
        "--max",
        str(max_threads),
        "--json",
        query,
    ]
    try:
        rc, out, err = _run(cmd, timeout_s=90)
    except subprocess.TimeoutExpired:
        return False, [], False, "gmail_search_timeout"

    if rc != 0:
        return False, [], False, f"gmail_search_failed rc={rc}"

    try:
        data = json.loads(out)
    except Exception:
        return False, [], False, "gmail_search_parse_failed"

    rows: List[ThreadRow] = []
    for t in data.get("threads") or []:
        tid = str(t.get("id") or "").strip()
        if not tid:
            continue
        rows.append(
            ThreadRow(
                id=tid,
                date=str(t.get("date") or "").strip(),
                from_=str(t.get("from") or "").strip(),
                subject=str(t.get("subject") or "").strip(),
                labels=list(t.get("labels") or []),
                message_count=int(t.get("messageCount") or 0),
            )
        )

    has_more = bool(data.get("nextPageToken"))
    return True, rows, has_more, ""


def _gog_list_labels(gog: str, account: str) -> Tuple[bool, Dict[str, str], str]:
    cmd = [gog, "gmail", "labels", "list", "--account", account, "--json"]
    try:
        rc, out, _err = _run(cmd, timeout_s=60)
    except subprocess.TimeoutExpired:
        return False, {}, "labels_list_timeout"
    if rc != 0:
        return False, {}, f"labels_list_failed rc={rc}"
    try:
        data = json.loads(out)
    except Exception:
        return False, {}, "labels_list_parse_failed"

    mapping: Dict[str, str] = {}
    for row in data.get("labels") or []:
        name = str(row.get("name") or "").strip()
        lid = str(row.get("id") or "").strip()
        if name and lid:
            mapping[name] = lid
    return True, mapping, ""


def _gog_create_label(gog: str, account: str, label: str) -> Tuple[bool, str]:
    cmd = [gog, "gmail", "labels", "create", label, "--account", account, "--json", "--no-input"]
    try:
        rc, _out, err = _run(cmd, timeout_s=60)
    except subprocess.TimeoutExpired:
        return False, "labels_create_timeout"
    if rc == 0:
        return True, ""

    # If label already exists, treat as success.
    if "already exists" in err.lower() or "duplicate" in err.lower():
        return True, ""
    return False, f"labels_create_failed rc={rc}"


def _gog_modify_thread(
    gog: str,
    account: str,
    thread_id: str,
    add: Sequence[str],
    remove: Sequence[str],
) -> Tuple[bool, str]:
    add_vals = sorted({x.strip() for x in add if x.strip()})
    rem_vals = sorted({x.strip() for x in remove if x.strip()})
    if not add_vals and not rem_vals:
        return True, ""

    cmd = [
        gog,
        "gmail",
        "thread",
        "modify",
        thread_id,
        "--account",
        account,
        "--json",
        "--no-input",
    ]
    if add_vals:
        cmd.extend(["--add", ",".join(add_vals)])
    if rem_vals:
        cmd.extend(["--remove", ",".join(rem_vals)])

    try:
        rc, _out, _err = _run(cmd, timeout_s=60)
    except subprocess.TimeoutExpired:
        return False, "thread_modify_timeout"
    if rc != 0:
        return False, f"thread_modify_failed rc={rc}"
    return True, ""


def _ensure_subagents(root: Path) -> None:
    _ensure_dir(root, 0o700)
    for slug, spec in SUBAGENT_TEMPLATES.items():
        d = root / slug
        _ensure_dir(d, 0o700)

        identity = d / "identity.md"
        policy = d / "policy.md"
        status = d / "status.md"
        runs = d / "runs.json"

        if not identity.exists():
            _atomic_write_text(identity, spec["identity"], mode=0o600)
        if not policy.exists():
            _atomic_write_text(policy, spec["policy"], mode=0o600)
        if not status.exists():
            _atomic_write_text(status, "# Status\n\nNo runs yet.\n", mode=0o600)
        if not runs.exists():
            _atomic_write_json(runs, {"version": 1, "runs": []}, mode=0o600)


def _update_subagent_run(
    root: Path,
    slug: str,
    run_id: str,
    started: dt.datetime,
    ended: dt.datetime,
    ok: bool,
    summary: Dict[str, Any],
) -> None:
    d = root / slug
    _ensure_dir(d, 0o700)

    status_path = d / "status.md"
    runs_path = d / "runs.json"

    status_text = "\n".join(
        [
            "# Status",
            "",
            f"Last Run ID: {run_id}",
            f"Started: {started.isoformat()}",
            f"Finished: {ended.isoformat()}",
            f"Result: {'ok' if ok else 'failed'}",
            "",
            "## Summary",
            "",
            f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)}\n```",
            "",
        ]
    )
    _atomic_write_text(status_path, status_text, mode=0o600)

    existing = _load_json(runs_path, {"version": 1, "runs": []})
    runs = existing.get("runs") if isinstance(existing, dict) else []
    if not isinstance(runs, list):
        runs = []

    runs.append(
        {
            "runId": run_id,
            "startedAt": started.isoformat(),
            "endedAt": ended.isoformat(),
            "ok": ok,
            "summary": summary,
        }
    )
    runs = runs[-200:]
    _atomic_write_json(runs_path, {"version": 1, "runs": runs}, mode=0o600)

    # Keep legacy/global overview in sync for operators that still read it.
    global_runs_path = root / "runs.json"
    global_state = _load_json(global_runs_path, {"version": 2, "runs": {}})
    if not isinstance(global_state, dict):
        global_state = {"version": 2, "runs": {}}
    runs_map = global_state.get("runs")
    if not isinstance(runs_map, dict):
        runs_map = {}
    runs_map[slug] = {
        "lastRunId": run_id,
        "lastRunAt": ended.isoformat(),
        "ok": ok,
    }
    global_state["version"] = 2
    global_state["runs"] = runs_map
    _atomic_write_json(global_runs_path, global_state, mode=0o600)


def _safe_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _single_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _detect_language_from_text(text: str) -> str:
    if not text:
        return ""
    has_hebrew = bool(HEBREW_CHAR_RE.search(text))
    has_latin = bool(LATIN_CHAR_RE.search(text))
    if has_latin and not has_hebrew:
        return "en"
    if has_hebrew:
        return "he"
    return ""


def _resolve_telegram_language(state: Dict[str, Any], notify_cfg: Dict[str, Any]) -> str:
    default_language = str(notify_cfg.get("defaultLanguage") or "he").strip().lower()
    if default_language not in {"he", "en"}:
        default_language = "he"

    # Explicit config override: force English.
    if default_language == "en":
        return "en"

    current_thread_id = str(state.get("current_thread_id") or "").strip()
    last_user_thread_id = str(state.get("last_user_thread_id") or "").strip()
    if current_thread_id and last_user_thread_id and current_thread_id == last_user_thread_id:
        last_user_language = str(state.get("last_user_language") or "").strip().lower()
        if last_user_language in {"he", "en"}:
            return last_user_language

        detected = _detect_language_from_text(str(state.get("last_user_text") or ""))
        if detected in {"he", "en"}:
            state["last_user_language"] = detected
            return detected

    return "he"


def _build_quiet_day_heartbeat(
    notify_cfg: Dict[str, Any],
    summary: Dict[str, Any],
    scanned: int,
    language: str,
) -> str:
    urgent = int(summary.get("urgent", 0))
    important = int(summary.get("important", 0))
    info = int(summary.get("info", 0))
    spam = int(summary.get("spam", 0))

    if language == "en":
        fallback_template = "Gmail triage: daily check. scanned={scanned}. urgent={urgent}. important={important}. info={info}. spam={spam}."
    else:
        fallback_template = "אימייל: בדיקה יומית. נסרקו {scanned}. דחוף={urgent}. חשוב={important}. מידע={info}. ספאם={spam}."

    template = str(notify_cfg.get("quietDayHeartbeatText") or "").strip() or fallback_template
    fmt = {
        "scanned": scanned,
        "urgent": urgent,
        "important": important,
        "info": info,
        "spam": spam,
    }
    try:
        text = template.format(**fmt)
    except Exception:
        text = fallback_template.format(**fmt)
    return _single_line(text)


def _apply_actions(
    *,
    gog: str,
    account: str,
    write_cfg: Dict[str, Any],
    actions: List[Action],
    errors: List[str],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    stats = {
        "attempted": 0,
        "label_success": 0,
        "archive_success": 0,
        "trash_success": 0,
        "failed": 0,
        "skipped_age": 0,
        "skipped_policy": 0,
        "byAction": {
            "label": {"attempted": 0, "succeeded": 0, "failed": 0, "skipped_age": 0, "skipped_policy": 0},
            "archive": {"attempted": 0, "succeeded": 0, "failed": 0, "skipped_age": 0, "skipped_policy": 0},
            "trash": {"attempted": 0, "succeeded": 0, "failed": 0, "skipped_age": 0, "skipped_policy": 0},
        },
    }
    audit: List[Dict[str, Any]] = []

    if not _safe_bool(write_cfg.get("enabled"), False):
        _json_log("INFO", "gmail_write_skipped", reason="write_disabled")
        return stats, audit

    label_enabled = _safe_bool((write_cfg.get("labels") or {}).get("enabled"), True)
    trash_cfg = write_cfg.get("trash") or {}
    trash_enabled = _safe_bool(trash_cfg.get("enabled"), False)
    policy_cfg = write_cfg.get("policy") or {}
    min_age_days = int(policy_cfg.get("minAgeDays") or 14)
    allowed_actions_raw = policy_cfg.get("allowedActions")
    if isinstance(allowed_actions_raw, list):
        allowed_actions = {str(v).strip().lower() for v in allowed_actions_raw if str(v).strip()}
    else:
        allowed_actions = {"label", "archive", "trash"}
    if not allowed_actions:
        allowed_actions = {"label", "archive", "trash"}

    required_labels = set()
    for action in actions:
        for label in action.add:
            if label.upper() in {"INBOX", "TRASH"}:
                continue
            required_labels.add(label)

    if label_enabled and required_labels:
        ok, existing, err = _gog_list_labels(gog, account)
        if not ok:
            errors.append(err)
            _json_log("WARN", "gmail_labels_list_failed", error=err)
            existing = {}
        for label in sorted(required_labels):
            if label in existing:
                continue
            ok_create, err_create = _gog_create_label(gog, account, label)
            if not ok_create:
                errors.append(err_create)
                _json_log("WARN", "gmail_label_create_failed", label=label, error=err_create)
            else:
                _json_log("INFO", "gmail_label_created", label=label)

    for action in actions[:DEFAULT_MAX_ACTIONS]:
        action_kind = action.kind.lower()
        if action_kind not in {"label", "archive", "trash"}:
            continue
        if action.kind == "label" and not label_enabled:
            continue
        if action.kind == "trash" and not trash_enabled:
            continue
        if action_kind not in allowed_actions:
            stats["skipped_policy"] += 1
            stats["byAction"][action_kind]["skipped_policy"] += 1
            _json_log(
                "INFO",
                "gmail_write_skipped_policy",
                action=action_kind,
                reason=action.reason,
                thread_id=action.thread_id,
            )
            audit.append(
                {
                    "action": action_kind,
                    "threadId": action.thread_id,
                    "reason": action.reason,
                    "status": "skipped_policy",
                    "ageDays": action.age_days,
                    "add": action.add,
                    "remove": action.remove,
                }
            )
            continue
        if action_kind in {"archive", "trash"} and (action.age_days is None or action.age_days < float(min_age_days)):
            stats["skipped_age"] += 1
            stats["byAction"][action_kind]["skipped_age"] += 1
            _json_log(
                "INFO",
                "gmail_write_skipped_age_gate",
                action=action_kind,
                reason=action.reason,
                thread_id=action.thread_id,
                age_days=action.age_days,
                min_age_days=min_age_days,
            )
            audit.append(
                {
                    "action": action_kind,
                    "threadId": action.thread_id,
                    "reason": action.reason,
                    "status": "skipped_age",
                    "ageDays": action.age_days,
                    "minAgeDays": min_age_days,
                    "add": action.add,
                    "remove": action.remove,
                }
            )
            continue

        stats["attempted"] += 1
        stats["byAction"][action_kind]["attempted"] += 1
        _json_log(
            "INFO",
            "gmail_write_attempt",
            action=action.kind,
            reason=action.reason,
            thread_id=action.thread_id,
        )

        ok, err = _gog_modify_thread(
            gog,
            account,
            action.thread_id,
            action.add,
            action.remove,
        )
        if not ok:
            stats["failed"] += 1
            stats["byAction"][action_kind]["failed"] += 1
            errors.append(err)
            _json_log(
                "WARN",
                "gmail_write_failed",
                action=action.kind,
                reason=action.reason,
                thread_id=action.thread_id,
                error=err,
            )
            audit.append(
                {
                    "action": action_kind,
                    "threadId": action.thread_id,
                    "reason": action.reason,
                    "status": "failed",
                    "error": err,
                    "ageDays": action.age_days,
                    "add": action.add,
                    "remove": action.remove,
                }
            )
            continue

        if action.kind == "label":
            stats["label_success"] += 1
        elif action.kind == "archive":
            stats["archive_success"] += 1
        elif action.kind == "trash":
            stats["trash_success"] += 1
        stats["byAction"][action_kind]["succeeded"] += 1

        _json_log(
            "INFO",
            "gmail_write_succeeded",
            action=action.kind,
            reason=action.reason,
            thread_id=action.thread_id,
        )
        audit.append(
            {
                "action": action_kind,
                "threadId": action.thread_id,
                "reason": action.reason,
                "status": "succeeded",
                "ageDays": action.age_days,
                "add": action.add,
                "remove": action.remove,
            }
        )

    return stats, audit


def _build_triage_actions(
    threads: List[ThreadRow],
    allowlist: List[Dict[str, Any]],
    write_cfg: Dict[str, Any],
    now_local: dt.datetime,
) -> Tuple[List[Action], Dict[str, Any], Dict[str, List[ThreadRow]]]:
    grouped: Dict[str, List[ThreadRow]] = {"URGENT": [], "IMPORTANT": [], "INFO": [], "SPAM": []}
    actions: List[Action] = []

    trash_cfg = write_cfg.get("trash") or {}
    spam_cfg = trash_cfg.get("spam") or {}
    newsletters_cfg = trash_cfg.get("newsletters") or {}

    spam_threshold = _safe_float(spam_cfg.get("minConfidence"), 0.95)
    spam_trash_enabled = _safe_bool(spam_cfg.get("enabled"), False)
    newsletter_trash_enabled = _safe_bool(newsletters_cfg.get("enabled"), False)

    by_id: Dict[str, ThreadRow] = {}

    for t in threads:
        by_id[t.id] = t
        priority = _classify_priority(t)
        grouped[priority].append(t)
        age_days = _compute_age_days(t.date, now_local)

        allow_match = _match_allowlist(t.from_, t.subject, allowlist)
        if allow_match:
            if allow_match.label not in t.labels:
                actions.append(
                    Action(
                        kind="label",
                        thread_id=t.id,
                        add=[allow_match.label],
                        remove=[],
                        reason=f"newsletter:{allow_match.source}",
                        age_days=age_days,
                    )
                )
            if newsletter_trash_enabled and "TRASH" not in t.labels:
                actions.append(
                    Action(
                        kind="trash",
                        thread_id=t.id,
                        add=["TRASH"],
                        remove=["INBOX"],
                        reason=f"newsletter_trash:{allow_match.source}",
                        age_days=age_days,
                    )
                )
            continue

        spam_score = _spam_confidence(t)
        if spam_score >= spam_threshold:
            if "SPAM_AUTO" not in t.labels:
                actions.append(
                    Action(
                        kind="label",
                        thread_id=t.id,
                        add=["SPAM_AUTO"],
                        remove=[],
                        reason="spam_auto",
                        confidence=spam_score,
                        age_days=age_days,
                    )
                )
            if spam_trash_enabled and "TRASH" not in t.labels:
                actions.append(
                    Action(
                        kind="trash",
                        thread_id=t.id,
                        add=["TRASH"],
                        remove=["INBOX"],
                        reason="spam_trash",
                        confidence=spam_score,
                        age_days=age_days,
                    )
                )
            continue

        route_label = _route_business_vs_personal(t)
        if route_label not in t.labels:
            actions.append(
                Action(
                    kind="label",
                    thread_id=t.id,
                    add=[route_label],
                    remove=[],
                    reason="thread_route",
                    age_days=age_days,
                )
            )

    summary = {
        "urgent": len(grouped["URGENT"]),
        "important": len(grouped["IMPORTANT"]),
        "info": len(grouped["INFO"]),
        "spam": len(grouped["SPAM"]),
        "invoices": sum(1 for t in threads if _is_invoice(t)),
        "actions_planned": len(actions),
    }

    return actions[:DEFAULT_MAX_ACTIONS], summary, grouped


def _should_send_telegram(health_errors: List[str], summary: Dict[str, Any], notify_cfg: Dict[str, Any]) -> bool:
    if health_errors:
        return True
    high_signal_only = _safe_bool(notify_cfg.get("highSignalOnly"), True)
    if not high_signal_only:
        return True
    return bool(summary.get("urgent") or summary.get("important") or summary.get("invoices"))


def _send_telegram(clawdbot_bin: str, chat_id: str, message: str) -> Tuple[bool, str]:
    send_cmd = [
        clawdbot_bin,
        "message",
        "send",
        "--channel",
        "telegram",
        "--account",
        "default",
        "--target",
        chat_id,
        "--message",
        message,
        "--json",
    ]

    rc_last = 1
    for attempt in range(1, 4):
        try:
            rc, _out, _err = _run(send_cmd, timeout_s=60)
        except subprocess.TimeoutExpired:
            rc = 124
        rc_last = rc
        if rc == 0:
            return True, ""
        time.sleep(2 * attempt)
    return False, f"telegram_send_failed rc={rc_last}"


def _check_scheduler_guard(home: Path, cfg: Dict[str, Any]) -> Dict[str, Any]:
    scheduler_cfg = cfg.get("scheduler") if isinstance(cfg, dict) else {}
    if not isinstance(scheduler_cfg, dict):
        scheduler_cfg = {}
    authority = str(scheduler_cfg.get("authority") or "systemd").strip().lower()
    disallowed_raw = scheduler_cfg.get("disallowedEnabledCronJobs")
    if isinstance(disallowed_raw, list):
        disallowed_names = [str(v).strip() for v in disallowed_raw if str(v).strip()]
    else:
        disallowed_names = ["gmail-plumber-daily", "newsletter-master-weekly"]

    result: Dict[str, Any] = {
        "authority": authority,
        "ok": True,
        "violations": [],
        "checkedJobs": disallowed_names,
        "error": "",
    }
    if authority != "systemd":
        return result

    clawdbot_bin = str(home / ".npm-global" / "bin" / "clawdbot")
    cmd = [clawdbot_bin, "cron", "list", "--all", "--json"]
    try:
        rc, out, _err = _run(cmd, timeout_s=60)
    except subprocess.TimeoutExpired:
        result["ok"] = False
        result["error"] = "scheduler_guard_timeout"
        return result
    if rc != 0:
        result["ok"] = False
        result["error"] = f"scheduler_guard_cli_failed rc={rc}"
        return result

    payload = _extract_json_payload(out)
    if not isinstance(payload, dict):
        result["ok"] = False
        result["error"] = "scheduler_guard_parse_failed"
        return result

    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        jobs = []
    bad: List[Dict[str, Any]] = []
    disallowed_set = {n for n in disallowed_names}
    for row in jobs:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        enabled = bool(row.get("enabled"))
        if name in disallowed_set and enabled:
            bad.append(
                {
                    "name": name,
                    "id": str(row.get("id") or ""),
                    "enabled": True,
                }
            )
    if bad:
        result["ok"] = False
        result["violations"] = bad
    return result


def _run_triage(
    *,
    args: argparse.Namespace,
    now: dt.datetime,
    run_id: str,
    state_file: Path,
    reports_dir: Path,
    allowlist: List[Dict[str, Any]],
    config: Dict[str, Any],
    errors: List[str],
    scheduler_guard: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any], Path]:
    now_epoch = int(now.timestamp())
    state = _load_json(state_file, {"version": 1, "last_run_epoch": 0})
    if not isinstance(state, dict):
        state = {"version": 1, "last_run_epoch": 0}

    query = "label:inbox"

    home = Path(os.environ.get("HOME", "/home/rotemgrosman"))
    gog = str(home / ".local" / "bin" / "gog")
    clawdbot_bin = str(home / ".npm-global" / "bin" / "clawdbot")

    ok, rows, has_more, err = _gog_search_threads(gog, args.account, query, args.max_threads)
    if not ok:
        errors.append(err)
        rows = []

    scanned_rows = rows

    actions, summary, grouped = _build_triage_actions(scanned_rows, allowlist, config.get("write") or {}, now)
    write_stats, write_audit = _apply_actions(
        gog=gog,
        account=args.account,
        write_cfg=config.get("write") or {},
        actions=actions,
        errors=errors,
    )

    report = {
        "run_id": run_id,
        "mode": "triage",
        "generated_at": now.isoformat(),
        "account": args.account,
        "query": query,
        "scanned": args.max_threads,
        "summary": summary,
        "writeStats": write_stats,
        "writeAudit": write_audit,
        "errors": errors,
        "schedulerGuard": scheduler_guard,
        "plan": [
            {
                "kind": a.kind,
                "threadId": a.thread_id,
                "add": a.add,
                "remove": a.remove,
                "reason": a.reason,
                "confidence": a.confidence,
                "ageDays": a.age_days,
            }
            for a in actions
        ],
        "new_threads": [
            {
                "id": t.id,
                "date": t.date,
                "from": t.from_,
                "subject": t.subject,
                "labels": t.labels,
                "messageCount": t.message_count,
            }
            for t in scanned_rows
        ],
        "telegram": {
            "sent": False,
            "reason": "pending",
        },
    }

    report_path = reports_dir / f"gmail-triage-{now:%Y%m%d-%H%M%S}.json"
    _atomic_write_json(report_path, report, mode=0o600)

    notify_cfg = ((config.get("notifications") or {}).get("telegram") or {})
    should_notify = _should_send_telegram(errors, summary, notify_cfg)
    output_language = _resolve_telegram_language(state, notify_cfg)

    telegram_sent = False
    telegram_reason = "quiet_day"
    quiet_day_mode = str(notify_cfg.get("quietDayMode") or "silent").strip().lower()
    if should_notify and not args.dry_run:
        message = _format_triage_digest(
            now_local=now,
            summary=summary,
            grouped=grouped,
            word_limit=args.word_limit,
            max_examples=int(notify_cfg.get("maxExamplesPerPriority") or 3),
            write_stats=write_stats,
            scanned=args.max_threads,
            language=output_language,
        )
        telegram_sent, tel_err = _send_telegram(clawdbot_bin, args.chat_id, message)
        if telegram_sent:
            telegram_reason = "high_signal"
            _json_log("INFO", "telegram_send_mode", channel="telegram", send_mode="text_high_signal")
        else:
            telegram_reason = "failed"
            errors.append(tel_err)
            _json_log("WARN", "telegram_send_failed", error=tel_err)
    elif should_notify and args.dry_run:
        telegram_reason = "dry_run"
    else:
        if quiet_day_mode == "heartbeat":
            heartbeat_text = _build_quiet_day_heartbeat(notify_cfg, summary, args.max_threads, output_language)
            if args.dry_run:
                telegram_reason = "quiet_day_heartbeat_dry_run"
            else:
                telegram_sent, tel_err = _send_telegram(clawdbot_bin, args.chat_id, heartbeat_text)
                if telegram_sent:
                    telegram_reason = "quiet_day_heartbeat"
                    _json_log("INFO", "telegram_send_mode", channel="telegram", send_mode="text_quiet_heartbeat")
                else:
                    telegram_reason = "failed"
                    errors.append(tel_err)
                    _json_log("WARN", "telegram_send_failed", error=tel_err)
        else:
            _json_log("INFO", "telegram_suppressed", reason="quiet_day")

    # Dedupe state: commit when delivery succeeded, dry-run, or quiet-day suppression.
    state_commit_ok = telegram_sent or args.dry_run or (not should_notify)
    if state_commit_ok:
        next_state = dict(state)
        next_state["version"] = 1
        next_state["account"] = args.account
        next_state["chat_id"] = args.chat_id
        next_state["last_run_epoch"] = now_epoch
        next_state["last_output_language"] = output_language
        _atomic_write_json(state_file, next_state, mode=0o600)

    report["errors"] = errors
    report["writeStats"] = write_stats
    report["writeAudit"] = write_audit
    report["summary"] = summary
    report["telegram"] = {"sent": telegram_sent, "reason": telegram_reason, "language": output_language}
    _atomic_write_json(report_path, report, mode=0o600)

    ok_result = ok and not errors and (telegram_sent or args.dry_run or not should_notify)
    result_summary = {
        "threads_seen": len(rows),
        "threads_new": len(scanned_rows),
        "scanned": args.max_threads,
        "urgent": summary.get("urgent", 0),
        "important": summary.get("important", 0),
        "info": summary.get("info", 0),
        "spam": summary.get("spam", 0),
        "invoices": summary.get("invoices", 0),
        "write_attempted": write_stats.get("attempted", 0),
        "write_failed": write_stats.get("failed", 0),
        "telegram_reason": telegram_reason,
        "scheduler_guard_ok": bool(scheduler_guard.get("ok")),
        "report": str(report_path),
    }
    return ok_result, result_summary, report_path


def _run_newsletter_weekly(
    *,
    args: argparse.Namespace,
    now: dt.datetime,
    run_id: str,
    reports_dir: Path,
    allowlist: List[Dict[str, Any]],
    config: Dict[str, Any],
    errors: List[str],
    scheduler_guard: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any], Path]:
    home = Path(os.environ.get("HOME", "/home/rotemgrosman"))
    gog = str(home / ".local" / "bin" / "gog")

    lookback_days = int(((config.get("newsletter") or {}).get("lookbackDays") or DEFAULT_NEWSLETTER_LOOKBACK_DAYS))
    query = f"newer_than:{lookback_days}d label:inbox"

    ok, rows, _has_more, err = _gog_search_threads(gog, args.account, query, max(args.max_threads, 200))
    if not ok:
        errors.append(err)
        rows = []

    matched: List[Tuple[ThreadRow, MatchedSource]] = []
    for thread in rows:
        source = _match_allowlist(thread.from_, thread.subject, allowlist)
        if source:
            matched.append((thread, source))

    digest_md = _format_newsletter_digest_md(now, matched)

    newsletter_dir = reports_dir / "newsletters"
    _ensure_dir(newsletter_dir, 0o700)
    digest_path = newsletter_dir / f"newsletter-digest-{now:%Y%m%d}.md"
    _atomic_write_text(digest_path, digest_md, mode=0o600)

    actions: List[Action] = []
    write_cfg = config.get("write") or {}
    newsletter_cfg = (write_cfg.get("trash") or {}).get("newsletters") or {}
    allow_trash = _safe_bool(write_cfg.get("enabled"), False) and _safe_bool(
        (write_cfg.get("trash") or {}).get("enabled"), False
    ) and _safe_bool(newsletter_cfg.get("enabled"), False)
    allowlist_only = _safe_bool(newsletter_cfg.get("allowlistOnly"), True)
    cleanup_days = int(newsletter_cfg.get("cleanupNonAllowlistedAfterDays") or lookback_days)
    cleanup_categories_raw = newsletter_cfg.get("cleanupCategories")
    if isinstance(cleanup_categories_raw, list):
        cleanup_categories = [str(v) for v in cleanup_categories_raw if str(v).strip()]
    else:
        cleanup_categories = ["CATEGORY_PROMOTIONS"]

    for thread, source in matched:
        age_days = _compute_age_days(thread.date, now)
        if source.label not in thread.labels:
            actions.append(
                Action(
                    kind="label",
                    thread_id=thread.id,
                    add=[source.label],
                    remove=[],
                    reason=f"newsletter_weekly:{source.source}",
                    age_days=age_days,
                )
            )
        if allow_trash and "TRASH" not in thread.labels:
            actions.append(
                Action(
                    kind="trash",
                    thread_id=thread.id,
                    add=["TRASH"],
                    remove=["INBOX"],
                    reason=f"newsletter_weekly_trash:{source.source}",
                    age_days=age_days,
                )
            )

    non_allowlisted_candidates = 0
    non_allowlisted_actions = 0
    if allow_trash and allowlist_only and cleanup_days > 0:
        cleanup_query = f"older_than:{cleanup_days}d label:inbox"
        ok_cleanup, cleanup_rows, _cleanup_more, cleanup_err = _gog_search_threads(
            gog,
            args.account,
            cleanup_query,
            max(args.max_threads, 300),
        )
        if not ok_cleanup:
            errors.append(cleanup_err)
            cleanup_rows = []

        for thread in cleanup_rows:
            if "TRASH" in thread.labels:
                continue
            if _match_allowlist(thread.from_, thread.subject, allowlist):
                continue
            if not _is_newsletter_cleanup_candidate(thread, cleanup_categories):
                continue
            non_allowlisted_candidates += 1
            non_allowlisted_actions += 1
            age_days = _compute_age_days(thread.date, now)
            actions.append(
                Action(
                    kind="trash",
                    thread_id=thread.id,
                    add=["TRASH"],
                    remove=["INBOX"],
                    reason="newsletter_cleanup_non_allowlisted",
                    age_days=age_days,
                )
            )

    write_stats, write_audit = _apply_actions(
        gog=gog,
        account=args.account,
        write_cfg=write_cfg,
        actions=actions,
        errors=errors,
    )

    report = {
        "run_id": run_id,
        "mode": "newsletter-weekly",
        "generated_at": now.isoformat(),
        "account": args.account,
        "query": query,
        "sources": sorted({source.source for _, source in matched}),
        "matched": len(matched),
        "writeStats": write_stats,
        "writeAudit": write_audit,
        "errors": errors,
        "digest": str(digest_path),
        "schedulerGuard": scheduler_guard,
        "nonAllowlistedCleanup": {
            "enabled": allow_trash and allowlist_only and cleanup_days > 0,
            "days": cleanup_days,
            "categories": [_normalize_category_label(v) for v in cleanup_categories],
            "candidates": non_allowlisted_candidates,
            "actions": non_allowlisted_actions,
        },
    }
    report_path = reports_dir / f"newsletter-weekly-{now:%Y%m%d-%H%M%S}.json"
    _atomic_write_json(report_path, report, mode=0o600)

    ok_result = ok and not errors
    result_summary = {
        "matched": len(matched),
        "sources": report["sources"],
        "write_attempted": write_stats.get("attempted", 0),
        "write_failed": write_stats.get("failed", 0),
        "non_allowlisted_cleanup_actions": non_allowlisted_actions,
        "digest": str(digest_path),
        "report": str(report_path),
    }
    return ok_result, result_summary, report_path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--account", required=True, help="Gmail account email")
    p.add_argument("--chat-id", required=True, help="Telegram chat id")
    p.add_argument("--mode", choices=["triage", "newsletter-weekly"], default="triage")
    p.add_argument("--max-threads", type=int, default=DEFAULT_MAX_THREADS)
    p.add_argument("--word-limit", type=int, default=DEFAULT_WORD_LIMIT)
    p.add_argument("--state-dir", default="", help="Override state dir (default: ~/jarvis-stack/jarvis-data/gmail-triage)")
    p.add_argument("--allowlist-path", default="", help="Override allowlist path")
    p.add_argument("--config-path", default="", help="Override triage config path")
    p.add_argument("--dry-run", action="store_true", help="No outbound telegram and no Gmail writes")
    args = p.parse_args()

    home = Path(os.environ.get("HOME", "/home/rotemgrosman"))
    state_dir = Path(args.state_dir) if args.state_dir else home / "jarvis-stack" / "jarvis-data" / "gmail-triage"
    allowlist_path = Path(args.allowlist_path) if args.allowlist_path else home / "jarvis-stack" / "jarvis-data" / "newsletters_allowlist.json"
    config_path = Path(args.config_path) if args.config_path else state_dir / "config.json"
    reports_dir = state_dir / "reports"
    state_file = state_dir / "state.json"
    lock_file = state_dir / "lock"
    subagents_root = home / ".clawdbot" / "subagents"

    _ensure_dir(state_dir, 0o700)
    _ensure_dir(reports_dir, 0o700)

    lock_fd = lock_file.open("w", encoding="utf-8")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0

    started = _now()
    run_id = f"{started:%Y%m%d-%H%M%S}-{os.getpid()}"
    errors: List[str] = []

    missing = _require_env_keys(["GOG_KEYRING_BACKEND", "GOG_KEYRING_PASSWORD"])
    if missing:
        errors.append(f"missing_env:{','.join(missing)}")

    allowlist = _load_allowlist(allowlist_path)
    config_raw = _load_json(config_path, {})
    config = _deep_merge(DEFAULT_CONFIG, config_raw if isinstance(config_raw, dict) else {})
    scheduler_guard = _check_scheduler_guard(home, config)
    if not scheduler_guard.get("ok", True):
        _json_log("ERROR", "scheduler_guard_violation", details=scheduler_guard)
        if _safe_bool(((config.get("scheduler") or {}).get("alertOnViolation")), True):
            errors.append("scheduler_guard_violation")

    if not _safe_bool((config.get("safety") or {}).get("allowPermanentDelete"), False):
        _json_log("INFO", "safety_mode", permanent_delete=False)

    _ensure_subagents(subagents_root)

    if args.dry_run:
        config["write"] = _deep_merge(config.get("write") or {}, {"enabled": False})

    if missing:
        _json_log("WARN", "env_missing", missing=missing)

    ok = False
    result_summary: Dict[str, Any] = {}
    report_path: Path

    _json_log("INFO", "gmail_triage_run_started", mode=args.mode, run_id=run_id)

    if args.mode == "triage":
        ok, result_summary, report_path = _run_triage(
            args=args,
            now=started,
            run_id=run_id,
            state_file=state_file,
            reports_dir=reports_dir,
            allowlist=allowlist,
            config=config,
            errors=errors,
            scheduler_guard=scheduler_guard,
        )
        slug = "gmail-plumber"
    else:
        ok, result_summary, report_path = _run_newsletter_weekly(
            args=args,
            now=started,
            run_id=run_id,
            reports_dir=reports_dir,
            allowlist=allowlist,
            config=config,
            errors=errors,
            scheduler_guard=scheduler_guard,
        )
        slug = "newsletter-master"

    ended = _now()
    result_summary["duration_ms"] = int((ended - started).total_seconds() * 1000)
    result_summary["errors"] = errors
    result_summary["report"] = str(report_path)

    _update_subagent_run(
        root=subagents_root,
        slug=slug,
        run_id=run_id,
        started=started,
        ended=ended,
        ok=ok,
        summary=result_summary,
    )

    _json_log(
        "INFO" if ok else "WARN",
        "gmail_triage_run_finished",
        mode=args.mode,
        run_id=run_id,
        ok=ok,
        report=str(report_path),
        errors_count=len(errors),
    )

    print(
        json.dumps(
            {
                "ok": ok,
                "mode": args.mode,
                "run_id": run_id,
                "report": str(report_path),
                "summary": result_summary,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
