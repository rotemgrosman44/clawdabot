#!/usr/bin/env python3
"""
Brief contract validator (PRD v10.4).

Validates:
- message.txt line count (exact or range)
- no blank lines
- status icon only at start of line 1 (🟢🟡🔴)
- header format: "<ICON> <PRODUCT> - YYYY-MM-DD"
- last line "SIGNAL <tokenized>" format (no JSON)
- signals.json required keys exist and are non-null / correct types

Usage examples:
  /usr/bin/python3 scripts/brief_validate.py \
    --product "MORNING BRIEF" --lines-exact 8 \
    --message /home/rotemgrosman/jarvis-stack/jarvis-data/morning-brief/message.txt \
    --signals /home/rotemgrosman/jarvis-stack/jarvis-data/morning-brief/signals.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ICONS = ("🟢", "🟡", "🔴")


def _fail(msg: str) -> int:
    sys.stderr.write(msg.rstrip() + "\n")
    return 2


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_message(
    *,
    product: str,
    message_path: Path,
    lines_exact: int | None,
    lines_min: int | None,
    lines_max: int | None,
    require_signal_prefix: str | None,
    signal_max_len: int,
) -> tuple[bool, list[str]]:
    errs: list[str] = []
    text = _read_text(message_path)
    lines = text.splitlines()

    # Placeholder scan (hard fail).
    if re.search(r"YYYY-MM-DD|\bunknown\b|<|>|\{YYYY|\{תאריך\}|\bX\b|\bY\b", text):
        errs.append("message contains placeholder token(s)")

    if any(not line.strip() for line in lines):
        errs.append("message has blank line(s)")

    if lines_exact is not None and len(lines) != lines_exact:
        errs.append(f"message line count {len(lines)} != {lines_exact}")
    if lines_min is not None and len(lines) < lines_min:
        errs.append(f"message line count {len(lines)} < {lines_min}")
    if lines_max is not None and len(lines) > lines_max:
        errs.append(f"message line count {len(lines)} > {lines_max}")

    if not lines:
        errs.append("message is empty")
        return (False, errs)

    # Emoji constraints: only allowed at start of line 1, and only these icons.
    if not any(lines[0].startswith(icon + " ") for icon in ICONS):
        errs.append("line 1 must start with a status icon (🟢🟡🔴) followed by a space")
    for i, line in enumerate(lines):
        for icon in ICONS:
            if icon in line:
                if not (i == 0 and line.startswith(icon + " ")):
                    errs.append(f"icon {icon} appears outside start of line 1")

    # Header format: "<ICON> <PRODUCT> - YYYY-MM-DD"
    header_re = re.compile(
        r"^[🟢🟡🔴] "
        + re.escape(product)
        + r" - \d{4}-\d{2}-\d{2}$"
    )
    if not header_re.match(lines[0]):
        errs.append("line 1 header does not match required format")

    if not lines[-1].startswith("SIGNAL "):
        errs.append("last line must start with SIGNAL ")
    else:
        last = lines[-1]
        if len(last) > signal_max_len:
            errs.append(f"SIGNAL line exceeds max length ({len(last)}>{signal_max_len})")
        if require_signal_prefix and not last.startswith(require_signal_prefix):
            errs.append("SIGNAL line missing required prefix")
        # Must be tokenized, not JSON.
        if "{" in last or "}" in last or "\"" in last:
            errs.append("SIGNAL line must not contain JSON")
        # Minimal token structure check.
        if not re.match(r"^SIGNAL [A-Z0-9]+\\|", last):
            errs.append("SIGNAL line must be tokenized (e.g., SIGNAL MB|...)")

    return (len(errs) == 0, errs)


def _validate_signals_json(
    *,
    signals_path: Path,
    product_token: str,
    require_week: bool,
) -> tuple[bool, list[str]]:
    errs: list[str] = []
    obj = _read_json(signals_path)
    if not isinstance(obj, dict):
        return (False, ["signals.json is not a JSON object"])

    def req(k: str, t: type) -> None:
        if k not in obj:
            errs.append(f"signals.json missing key: {k}")
            return
        v = obj.get(k)
        if t is int:
            if not isinstance(v, int):
                errs.append(f"signals.json key {k} is not int")
        elif t is str:
            if not isinstance(v, str):
                errs.append(f"signals.json key {k} is not string")
        else:
            if not isinstance(v, t):
                errs.append(f"signals.json key {k} is not {t.__name__}")

    req("product", str)
    req("status", str)
    req("errors", int)
    req("error_reason", str)

    if obj.get("product") != product_token:
        errs.append(f"signals.json product != {product_token}")

    if require_week:
        req("week", str)
    else:
        req("date", str)

    # Common numeric keys for brief-style products (required by v11.0).
    for k in ("emails", "urgent", "invoices"):
        req(k, int)

    return (len(errs) == 0, errs)


def _validate_report_json(
    *,
    report_path: Path,
    min_items: int | None,
    require_report_url: bool,
    require_top3: bool,
) -> tuple[bool, list[str]]:
    errs: list[str] = []
    obj = _read_json(report_path)
    if not isinstance(obj, dict):
        return (False, ["report.json is not a JSON object"])

    items = obj.get("items") if isinstance(obj.get("items"), list) else []
    if min_items is not None and int(min_items) > 0 and len(items) < int(min_items):
        errs.append(f"report.items length {len(items)} < {int(min_items)}")

    if require_report_url:
        url = obj.get("report_url")
        if not isinstance(url, str) or not url.strip() or url.strip() == "none":
            errs.append("report.report_url missing")

    if require_top3:
        top3 = obj.get("top3") if isinstance(obj.get("top3"), list) else []
        if len(top3) != 3:
            errs.append("report.top3 must be length 3")
        else:
            seen: set[str] = set()
            for it in top3:
                if not isinstance(it, dict):
                    errs.append("report.top3 entries must be objects")
                    continue
                top_tag = it.get("top_tag")
                if top_tag not in ("TOP-1", "TOP-2", "TOP-3"):
                    errs.append("top3 missing/invalid top_tag")
                else:
                    if top_tag in seen:
                        errs.append("duplicate top_tag in top3")
                    seen.add(top_tag)
                if not isinstance(it.get("category"), str) or not str(it.get("category") or "").strip():
                    errs.append("top3 missing category")
                if not isinstance(it.get("id"), str) or not str(it.get("id") or "").strip() or it.get("id") == "none":
                    errs.append("top3 missing id")

    return (len(errs) == 0, errs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True, help='Header product token, e.g. "MORNING BRIEF"')
    ap.add_argument("--product-token", required=True, help='signals.json product token, e.g. "MORNING_BRIEF"')
    ap.add_argument("--message", required=True)
    ap.add_argument("--signals", required=True)
    ap.add_argument("--report", default="", help="Optional report.json path for additional validation")
    ap.add_argument("--lines-exact", type=int, default=None)
    ap.add_argument("--lines-min", type=int, default=None)
    ap.add_argument("--lines-max", type=int, default=None)
    ap.add_argument("--require-week", action="store_true")
    ap.add_argument("--require-signal-prefix", default=None)
    ap.add_argument("--signal-max-len", type=int, default=120)
    ap.add_argument("--min-report-items", type=int, default=0)
    ap.add_argument("--require-report-url", action="store_true")
    ap.add_argument("--require-top3", action="store_true")
    args = ap.parse_args()

    msg_ok, msg_errs = _validate_message(
        product=args.product,
        message_path=Path(args.message),
        lines_exact=args.lines_exact,
        lines_min=args.lines_min,
        lines_max=args.lines_max,
        require_signal_prefix=args.require_signal_prefix,
        signal_max_len=int(args.signal_max_len),
    )
    sig_ok, sig_errs = _validate_signals_json(
        signals_path=Path(args.signals),
        product_token=args.product_token,
        require_week=bool(args.require_week),
    )

    rep_ok = True
    rep_errs: list[str] = []
    if args.report:
        rep_ok, rep_errs = _validate_report_json(
            report_path=Path(args.report),
            min_items=int(args.min_report_items) if int(args.min_report_items) > 0 else None,
            require_report_url=bool(args.require_report_url),
            require_top3=bool(args.require_top3),
        )

    if not msg_ok:
        sys.stderr.write("MESSAGE_VALIDATION_FAIL\n")
        for e in msg_errs:
            sys.stderr.write(f"- {e}\n")
    if not sig_ok:
        sys.stderr.write("SIGNALS_VALIDATION_FAIL\n")
        for e in sig_errs:
            sys.stderr.write(f"- {e}\n")
    if not rep_ok:
        sys.stderr.write("REPORT_VALIDATION_FAIL\n")
        for e in rep_errs:
            sys.stderr.write(f"- {e}\n")

    if msg_ok and sig_ok and rep_ok:
        sys.stdout.write("OK\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
