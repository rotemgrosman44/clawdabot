#!/usr/bin/env python3
from __future__ import annotations

import sys
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canon_guard_lib import (
    CmdResult,
    atomic_write_json,
    atomic_write_text,
    md_codeblock,
    md_section,
    run_cmd,
    status_rollup,
    utc_now_iso,
)


JARVIS_DATA = Path("/home/rotemgrosman/jarvis-stack/jarvis-data")
LEDGER_DIR = JARVIS_DATA / "gmail-triage" / "reports"
GMAIL_CONFIG = JARVIS_DATA / "gmail-triage" / "config.json"

DERIVED_CONTRACTS = [
    {
        "name": "morning-brief",
        "message": JARVIS_DATA / "morning-brief" / "message.txt",
        "signals": JARVIS_DATA / "morning-brief" / "signals.json",
        "lines": {"kind": "exact", "n": 8},
        "signal_prefix": "SIGNAL MB|",
    },
    {
        "name": "eod",
        "message": JARVIS_DATA / "eod" / "message.txt",
        "signals": JARVIS_DATA / "eod" / "signals.json",
        "lines": {"kind": "range", "min": 12, "max": 15},
        "signal_prefix": "SIGNAL EOD|",
    },
    {
        "name": "weekly-top3",
        "message": JARVIS_DATA / "weekly-top3" / "message.txt",
        "signals": JARVIS_DATA / "weekly-top3" / "signals.json",
        "lines": {"kind": "exact", "n": 6},
        "signal_prefix": "SIGNAL W|",
    },
]


NEWSLETTER_STANDARD = {
    "archive_root": JARVIS_DATA / "archive" / "newsletter-weekly",
    "latest_link": JARVIS_DATA / "newsletter-weekly" / "latest",
    "required_files": [
        "telegram_message.txt",
        "report.json",
        "report.md",
        "signals.json",
        "evidence.json",
    ],
    "legacy_flat_dir": JARVIS_DATA / "newsletter-weekly",
    "legacy_flat_files": ["message.txt", "signals.json", "report.json", "report.md"],
}


def _line_count(path: Path) -> Optional[int]:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except Exception:
        return None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jq_keys(path: Path) -> Tuple[Optional[List[str]], Optional[str]]:
    # Avoid printing values from artifacts; only record top-level keys.
    try:
        data = _read_json(path)
    except Exception as exc:
        return None, f"json_read_failed:{exc}"
    if not isinstance(data, dict):
        return None, "json_not_object"
    keys = sorted([str(k) for k in data.keys()])
    return keys, None


def run(out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    checks: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []

    # Safety posture (binding): SAFE_READONLY default.
    cfg_obj: Dict[str, Any] = {}
    if GMAIL_CONFIG.exists():
        try:
            raw = _read_json(GMAIL_CONFIG)
            cfg_obj = raw if isinstance(raw, dict) else {}
        except Exception:
            cfg_obj = {}

    write_cfg = cfg_obj.get("write") if isinstance(cfg_obj.get("write"), dict) else {}
    safety_cfg = cfg_obj.get("safety") if isinstance(cfg_obj.get("safety"), dict) else {}
    write_enabled = bool(write_cfg.get("enabled")) if isinstance(write_cfg, dict) else False
    write_flag = str(write_cfg.get("featureFlag") or "") if isinstance(write_cfg, dict) else ""
    allow_perm_delete = bool(safety_cfg.get("allowPermanentDelete")) if isinstance(safety_cfg, dict) else False

    checks.append(
        {
            "id": "safety_config_present",
            "status": "PASS" if GMAIL_CONFIG.exists() else "FAIL",
            "detail": str(GMAIL_CONFIG),
        }
    )
    checks.append(
        {
            "id": "safety_safe_readonly_write_disabled",
            "status": "PASS" if (GMAIL_CONFIG.exists() and not write_enabled) else "FAIL",
            "detail": f"write.enabled={write_enabled}",
        }
    )
    # If writes are enabled (non-canon), require explicit feature flag acknowledgement.
    if GMAIL_CONFIG.exists() and write_enabled:
        expected = "I_UNDERSTAND_GMAIL_WRITES"
        checks.append(
            {
                "id": "safety_write_feature_flag_present",
                "status": "PASS" if write_flag == expected else "FAIL",
                "detail": f"write.featureFlag={write_flag or 'missing'} expected={expected}",
            }
        )
    checks.append(
        {
            "id": "safety_no_permanent_delete",
            "status": "PASS" if (GMAIL_CONFIG.exists() and not allow_perm_delete) else "FAIL",
            "detail": f"safety.allowPermanentDelete={allow_perm_delete}",
        }
    )

    # Ledger presence
    ledger_exists = LEDGER_DIR.exists()
    checks.append({"id": "ledger_dir_exists", "status": "PASS" if ledger_exists else "FAIL", "detail": str(LEDGER_DIR)})

    latest_triage = sorted(LEDGER_DIR.glob("gmail-triage-*.json"))[-1] if ledger_exists and list(LEDGER_DIR.glob("gmail-triage-*.json")) else None
    latest_newsletter = (
        sorted(LEDGER_DIR.glob("newsletter-weekly-*.json"))[-1]
        if ledger_exists and list(LEDGER_DIR.glob("newsletter-weekly-*.json"))
        else None
    )

    checks.append(
        {
            "id": "ledger_latest_triage_report_present",
            "status": "PASS" if latest_triage else ("FAIL" if ledger_exists else "FAIL"),
            "detail": str(latest_triage) if latest_triage else "missing",
        }
    )
    checks.append(
        {
            "id": "ledger_latest_newsletter_report_present",
            "status": "PASS" if latest_newsletter else ("WARN" if ledger_exists else "FAIL"),
            "detail": str(latest_newsletter) if latest_newsletter else "missing",
        }
    )

    # Derived products contract checks (message line count + signals token prefix).
    derived_results = []
    for c in DERIVED_CONTRACTS:
        msg_path: Path = c["message"]
        sig_path: Path = c["signals"]

        msg_ok = msg_path.exists()
        sig_ok = sig_path.exists()

        msg_lines = _line_count(msg_path) if msg_ok else None
        sig_keys, sig_err = (_jq_keys(sig_path) if sig_ok else (None, "missing"))
        sig_token = ""
        if sig_ok and sig_err is None:
            try:
                sig_obj = _read_json(sig_path)
                sig_token = str(sig_obj.get("signal_token") or "")
            except Exception:
                sig_token = ""

        # Line contract
        lines_cfg = c["lines"]
        lines_status = "FAIL"
        lines_detail = "missing"
        if msg_ok and msg_lines is not None:
            if lines_cfg["kind"] == "exact":
                ok = msg_lines == int(lines_cfg["n"])
                lines_status = "PASS" if ok else "FAIL"
                lines_detail = f"lines={msg_lines} expected={lines_cfg['n']}"
            else:
                ok = int(lines_cfg["min"]) <= msg_lines <= int(lines_cfg["max"])
                lines_status = "PASS" if ok else "FAIL"
                lines_detail = f"lines={msg_lines} expected_range=[{lines_cfg['min']},{lines_cfg['max']}]"

        # SIGNAL token prefix
        prefix = str(c["signal_prefix"])
        token_ok = sig_token.startswith(prefix) if sig_token else False
        token_status = "PASS" if token_ok else ("FAIL" if sig_ok else "FAIL")

        checks.append({"id": f"derived_message_lines:{c['name']}", "status": lines_status, "detail": lines_detail})
        checks.append(
            {
                "id": f"derived_signal_token_prefix:{c['name']}",
                "status": token_status,
                "detail": f"signal_token_prefix_expected={prefix}",
            }
        )
        derived_results.append(
            {
                "name": c["name"],
                "message": str(msg_path),
                "signals": str(sig_path),
                "message_lines": msg_lines,
                "signal_token": sig_token,
                "signals_keys": sig_keys,
                "signals_error": sig_err,
            }
        )

    # Newsletter weekly standard checks.
    arch_root: Path = NEWSLETTER_STANDARD["archive_root"]
    latest_link: Path = NEWSLETTER_STANDARD["latest_link"]
    legacy_dir: Path = NEWSLETTER_STANDARD["legacy_flat_dir"]

    checks.append({"id": "newsletter_archive_root_exists", "status": "PASS" if arch_root.exists() else "FAIL", "detail": str(arch_root)})

    latest_exists = latest_link.exists() or latest_link.is_symlink()

    # Legacy flat files are forbidden as real files. Symlinks are allowed for compatibility.
    legacy_present_real: List[str] = []
    if legacy_dir.exists():
        for fn in NEWSLETTER_STANDARD["legacy_flat_files"]:
            p = legacy_dir / fn
            if p.exists() and not p.is_symlink():
                legacy_present_real.append(fn)

    if not latest_exists and legacy_present_real:
        latest_status = "FAIL"  # ambiguous legacy state (flat exists, latest missing)
    elif not latest_exists:
        latest_status = "WARN"  # no successful pipeline run yet
    else:
        latest_status = "PASS"

    checks.append({"id": "newsletter_latest_symlink_exists", "status": latest_status, "detail": str(latest_link)})

    required = list(NEWSLETTER_STANDARD["required_files"])
    latest_target = None
    required_missing: List[str] = []
    if latest_exists and latest_link.is_symlink():
        try:
            latest_target = latest_link.resolve()
        except Exception:
            latest_target = None
    if latest_target and isinstance(latest_target, Path) and latest_target.exists():
        for fn in required:
            if not (latest_target / fn).exists():
                required_missing.append(fn)

    if not latest_exists:
        required_status = "WARN" if not legacy_present_real else "FAIL"
    elif latest_target is None:
        required_status = "FAIL"
    elif required_missing:
        required_status = "FAIL"
    else:
        required_status = "PASS"

    checks.append(
        {
            "id": "newsletter_latest_required_files",
            "status": required_status,
            "detail": f"latest_target={str(latest_target) if latest_target else 'none'} missing={len(required_missing)}",
            "missing": required_missing,
        }
    )

    legacy_status = "FAIL" if legacy_present_real else "PASS"
    checks.append(
        {
            "id": "newsletter_legacy_flat_present",
            "status": legacy_status,
            "detail": f"legacy_dir={legacy_dir} real_files_present={len(legacy_present_real)}",
            "files_present": legacy_present_real,
        }
    )

    # Validate newsletter weekly contract if latest is present and looks valid.
    nw_contract_errors: List[str] = []
    nw_items_len: Optional[int] = None
    nw_top3_len: Optional[int] = None
    nw_signal_prefix_ok: Optional[bool] = None
    nw_msg_lines: Optional[int] = None
    if latest_target and required_status == "PASS":
        msg_path = latest_target / "telegram_message.txt"
        sig_path = latest_target / "signals.json"
        rep_path = latest_target / "report.json"

        try:
            msg_text = msg_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            msg_text = ""
        nw_msg_lines = len(msg_text.splitlines()) if msg_text else None
        if nw_msg_lines != 6:
            nw_contract_errors.append(f"telegram_message_lines={nw_msg_lines} expected=6")
        # Contract: message must include a SIGNAL line (validator uses require-signal-prefix).
        lines = msg_text.splitlines() if msg_text else []
        sig_lines = [ln for ln in lines if ln.startswith("SIGNAL NW|")]
        nw_signal_prefix_ok = bool(sig_lines)
        if not nw_signal_prefix_ok:
            nw_contract_errors.append("telegram_message_missing_SIGNAL_NW_prefix")
        else:
            if any(len(ln) > 120 for ln in sig_lines):
                nw_contract_errors.append("signal_line_too_long")
        try:
            _ = _read_json(sig_path)
        except Exception:
            nw_contract_errors.append("signals_json_read_failed")
        try:
            rep_obj = _read_json(rep_path)
            if isinstance(rep_obj, dict):
                items = rep_obj.get("items") if isinstance(rep_obj.get("items"), list) else []
                top3 = rep_obj.get("top3") if isinstance(rep_obj.get("top3"), list) else []
                nw_items_len = len(items)
                nw_top3_len = len(top3)
        except Exception:
            nw_contract_errors.append("report_json_read_failed")
        if nw_items_len is None or not (10 <= int(nw_items_len) <= 15):
            nw_contract_errors.append(f"items_len_out_of_range:{nw_items_len}")
        if nw_top3_len is None or int(nw_top3_len) != 3:
            nw_contract_errors.append(f"top3_len_not_3:{nw_top3_len}")

    checks.append(
        {
            "id": "newsletter_weekly_contract_latest",
            "status": "PASS" if (latest_target and required_status == "PASS" and not nw_contract_errors) else ("WARN" if not latest_exists and not legacy_present_real else "FAIL"),
            "detail": f"errors={len(nw_contract_errors)}",
            "errors": nw_contract_errors,
        }
    )

    overall = status_rollup([c["status"] for c in checks])
    report = {
        "kind": "canon_guard_artifacts",
        "generated_at": utc_now_iso(),
        "overall_status": overall,
        "ledger_dir": str(LEDGER_DIR),
        "latest_reports": {
            "triage": str(latest_triage) if latest_triage else "",
            "newsletter_weekly": str(latest_newsletter) if latest_newsletter else "",
        },
        "derived": derived_results,
        "newsletter_weekly": {
            "archive_root": str(arch_root),
            "latest_link": str(latest_link),
            "latest_target": str(latest_target) if latest_target else "",
            "required_files": required,
            "required_missing": required_missing,
            "legacy_flat_dir": str(legacy_dir),
            "legacy_flat_files_present": legacy_present_real,
            "latest_contract": {
                "telegram_message_lines": nw_msg_lines,
                "telegram_signal_prefix_ok": nw_signal_prefix_ok,
                "items_len": nw_items_len,
                "top3_len": nw_top3_len,
                "errors": nw_contract_errors,
            },
        },
        "checks": checks,
        "evidence": evidence,
    }

    md = "# Canon Guard: Artifacts\n\n"
    md += md_section("Overall", f"- status: `{overall}`\n- generated_at: `{report['generated_at']}`")
    md += md_section(
        "Ledger",
        "\n".join(
            [
                f"- dir: `{LEDGER_DIR}` exists={ledger_exists}",
                f"- latest triage: `{report['latest_reports']['triage'] or 'missing'}`",
                f"- latest newsletter-weekly: `{report['latest_reports']['newsletter_weekly'] or 'missing'}`",
            ]
        ),
    )
    md += md_section(
        "Derived Products",
        md_codeblock("\n".join([f"{d['name']}\tlines={d['message_lines']}\tsignal={d['signal_token'][:20]}..." for d in derived_results])),
    )
    md += md_section(
        "Newsletter Weekly (Archive Standard)",
        "\n".join(
            [
                f"- archive_root: `{arch_root}` exists={arch_root.exists()}",
                f"- latest_link: `{latest_link}` exists={latest_exists}",
                f"- latest_target: `{str(latest_target) if latest_target else 'none'}`",
                f"- required_missing: `{len(required_missing)}`",
                f"- legacy_flat_real_files_present: `{len(legacy_present_real)}`",
            ]
        ),
    )
    md += md_section("Checks", md_codeblock("\n".join([f"{c['status']}\t{c['id']}\t{c.get('detail','')}" for c in checks])))

    atomic_write_json(out_dir / "artifacts_contract_report.json", report)
    atomic_write_text(out_dir / "artifacts_contract_report.md", md)
    return report


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="", help="Output directory (default: current working dir)")
    args = ap.parse_args()
    out = Path(args.out_dir) if args.out_dir else Path.cwd()
    rep = run(out)
    raise SystemExit(0 if rep.get("overall_status") in ("PASS", "WARN") else 2)
