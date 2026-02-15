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


SYSTEMD_TIMERS = [
    "clawdbot-gmail-triage.timer",
    "clawdbot-newsletter-master.timer",
]

SYSTEMD_SERVICES = [
    "clawdbot-gmail-triage.service",
    "clawdbot-newsletter-master.service",
]

DUPLICATE_INTENT_CRON_JOBS = [
    "gmail-plumber-daily",
    "newsletter-master-weekly",
    "daily-morning-report",
]

ALLOWED_TELEGRAM_DELIVERY_CRON_JOBS = [
    "morning-brief",
    "end-of-day-summary",
    "weekly-top3",
]


def _systemd_is_enabled(unit: str) -> Tuple[bool, CmdResult]:
    res = run_cmd(["systemctl", "--user", "is-enabled", unit], timeout_s=30)
    enabled = res.rc == 0 and res.stdout.strip() == "enabled"
    return enabled, res


def _systemd_cat(units: List[str]) -> CmdResult:
    return run_cmd(["systemctl", "--user", "cat", *units], timeout_s=30)


def _read_cron_jobs_json(timeout_ms: int = 60000) -> Tuple[Optional[Dict[str, Any]], CmdResult]:
    env = os.environ.copy()
    # In this stack, clawdbot is installed in ~/.npm-global/bin.
    env["PATH"] = "/home/rotemgrosman/.npm-global/bin:" + env.get("PATH", "")
    res = run_cmd(
        ["clawdbot", "cron", "list", "--all", "--json", "--timeout", str(timeout_ms)],
        timeout_s=90,
        env=env,
    )
    if res.rc != 0:
        return None, res
    try:
        data = json.loads(res.stdout)
    except Exception:
        return None, CmdResult(cmd=res.cmd, rc=2, stdout=res.stdout, stderr=(res.stderr + "\njson_parse_failed").strip())
    if not isinstance(data, dict):
        return None, CmdResult(cmd=res.cmd, rc=2, stdout=res.stdout, stderr=(res.stderr + "\njson_not_object").strip())
    return data, res


def run(out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    evidence: List[Dict[str, Any]] = []
    checks: List[Dict[str, Any]] = []

    # systemd timer enablement is a hard invariant.
    sysd_status = {}
    for unit in SYSTEMD_TIMERS:
        enabled, res = _systemd_is_enabled(unit)
        evidence.append(
            {
                "kind": "cmd",
                "name": f"systemd_is_enabled:{unit}",
                "cmd": res.cmd,
                "rc": res.rc,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
            }
        )
        sysd_status[unit] = {"enabled": bool(enabled), "stdout": res.stdout.strip(), "rc": res.rc}
        checks.append(
            {
                "id": f"systemd_timer_enabled:{unit}",
                "status": "PASS" if enabled else "FAIL",
                "detail": res.stdout.strip() or res.stderr.strip() or "no_output",
            }
        )

    # Snapshot unit text (evidence) but do not include env values.
    cat_units = SYSTEMD_TIMERS + SYSTEMD_SERVICES
    cat_res = _systemd_cat(cat_units)
    evidence.append(
        {
            "kind": "cmd",
            "name": "systemd_cat_units",
            "cmd": cat_res.cmd,
            "rc": cat_res.rc,
            "stdout": cat_res.stdout,
            "stderr": cat_res.stderr.strip(),
        }
    )
    atomic_write_text(out_dir / "systemd_units.txt", cat_res.stdout + (("\n" + cat_res.stderr) if cat_res.stderr else ""))

    # Cron: hard invariants about duplication and Telegram delivery allowlist.
    cron_data, cron_res = _read_cron_jobs_json()
    evidence.append(
        {
            "kind": "cmd",
            "name": "clawdbot_cron_list_all_json",
            "cmd": cron_res.cmd,
            "rc": cron_res.rc,
            "stdout_bytes": len(cron_res.stdout.encode("utf-8", errors="ignore")),
            "stderr": cron_res.stderr.strip(),
        }
    )
    if cron_res.rc == 0 and cron_data is not None:
        atomic_write_text(out_dir / "cron_list_all.json", json.dumps(cron_data, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
    else:
        atomic_write_text(out_dir / "cron_list_all.json", cron_res.stdout)
        atomic_write_text(out_dir / "cron_list_all.stderr", cron_res.stderr)

    jobs: List[Dict[str, Any]] = []
    if cron_data and isinstance(cron_data.get("jobs"), list):
        jobs = [j for j in cron_data["jobs"] if isinstance(j, dict)]

    def find_job(name: str) -> Optional[Dict[str, Any]]:
        for j in jobs:
            if str(j.get("name") or "") == name:
                return j
        return None

    # Duplicate cron jobs: PASS if absent or disabled; FAIL if enabled.
    for name in DUPLICATE_INTENT_CRON_JOBS:
        j = find_job(name)
        if j is None:
            checks.append({"id": f"cron_duplicate_intent_disabled:{name}", "status": "PASS", "detail": "absent"})
            continue
        enabled = bool(j.get("enabled"))
        checks.append(
            {
                "id": f"cron_duplicate_intent_disabled:{name}",
                "status": "FAIL" if enabled else "PASS",
                "detail": "enabled" if enabled else "disabled",
                "job_id": j.get("id"),
            }
        )

    # Telegram delivery: only allow listed jobs to deliver to telegram.
    delivering = []
    for j in jobs:
        payload = j.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("deliver") is True and str(payload.get("channel") or "") == "telegram":
            delivering.append(
                {
                    "id": j.get("id"),
                    "name": j.get("name"),
                    "enabled": bool(j.get("enabled")),
                    "payload_kind": payload.get("kind"),
                    "to": payload.get("to"),
                }
            )
    unexpected = [d for d in delivering if str(d.get("name") or "") not in set(ALLOWED_TELEGRAM_DELIVERY_CRON_JOBS)]
    checks.append(
        {
            "id": "cron_telegram_delivery_allowlist",
            "status": "FAIL" if unexpected else "PASS",
            "detail": f"telegram_delivering_jobs={len(delivering)} unexpected={len(unexpected)}",
            "unexpected": unexpected,
            "delivering": delivering,
        }
    )

    # Verify that the allowlisted jobs (if present) are agentTurn + deliver=true.
    for name in ALLOWED_TELEGRAM_DELIVERY_CRON_JOBS:
        j = find_job(name)
        if j is None:
            checks.append({"id": f"cron_job_present:{name}", "status": "WARN", "detail": "absent"})
            continue
        payload = j.get("payload") if isinstance(j.get("payload"), dict) else {}
        ok = payload.get("kind") in ("agentTurn",) and payload.get("deliver") is True and payload.get("channel") == "telegram"
        checks.append(
            {
                "id": f"cron_brief_contract_shape:{name}",
                "status": "PASS" if ok else "WARN",
                "detail": f"payload.kind={payload.get('kind')} deliver={payload.get('deliver')} channel={payload.get('channel')}",
                "job_id": j.get("id"),
            }
        )

    statuses = [c["status"] for c in checks]
    overall = status_rollup(statuses)

    report = {
        "kind": "canon_guard_scheduler",
        "generated_at": utc_now_iso(),
        "overall_status": overall,
        "systemd": sysd_status,
        "cron": {
            "duplicate_intent_jobs": DUPLICATE_INTENT_CRON_JOBS,
            "allowed_telegram_delivery_jobs": ALLOWED_TELEGRAM_DELIVERY_CRON_JOBS,
            "jobs_count": len(jobs),
        },
        "checks": checks,
        "evidence": evidence,
    }

    # Human report
    md = "# Canon Guard: Scheduler\n\n"
    md += md_section("Overall", f"- status: `{overall}`\n- generated_at: `{report['generated_at']}`")
    md += md_section(
        "Systemd Timers",
        "\n".join([f"- `{u}`: enabled={sysd_status[u]['enabled']}" for u in SYSTEMD_TIMERS]),
    )
    md += md_section(
        "Cron Invariants",
        "\n".join(
            [
                "- duplicate intent cron jobs must be disabled: "
                + ", ".join([f"`{n}`" for n in DUPLICATE_INTENT_CRON_JOBS]),
                "- telegram delivery allowlist: " + ", ".join([f"`{n}`" for n in ALLOWED_TELEGRAM_DELIVERY_CRON_JOBS]),
            ]
        ),
    )
    md += md_section("Checks", md_codeblock("\n".join([f"{c['status']}\t{c['id']}\t{c.get('detail','')}" for c in checks])))

    atomic_write_json(out_dir / "scheduler_guard_report.json", report)
    atomic_write_text(out_dir / "scheduler_guard_report.md", md)

    return report


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="", help="Output directory (default: current working dir)")
    args = ap.parse_args()
    out = Path(args.out_dir) if args.out_dir else Path.cwd()
    rep = run(out)
    raise SystemExit(0 if rep.get("overall_status") in ("PASS", "WARN") else 2)
