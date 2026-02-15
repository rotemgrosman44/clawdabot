#!/usr/bin/env python3
"""
Canon enforcement checker (read-only).

Writes a report to:
  /home/rotemgrosman/jarvis-stack/jarvis-data/audit/canon-check/latest/

Hard rules (governance PRD):
- No external side effects (no Telegram, no Drive, no Gmail writes).
- Detect scheduler drift (systemd vs cron) for overlapping intents.
- Validate presence of canonical paths and key files.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


JARVIS_DATA = Path("/home/rotemgrosman/jarvis-stack/jarvis-data")
AUDIT_ROOT = JARVIS_DATA / "audit" / "canon-check"
LATEST_DIR = AUDIT_ROOT / "latest"

CRON_JOBS_JSON = Path("/home/rotemgrosman/.clawdbot/cron/jobs.json")
WORKFLOWS_SOT = Path("/home/rotemgrosman/clawd/workflows")
WORKFLOWS_LEGACY = Path("/home/rotemgrosman/jarvis-stack/jarvis-data/workflows")
GMAIL_TRIAGE_CONFIG = Path("/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/config.json")
TAG_MAP = Path("/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/config/tag_map.json")

SYSTEMD_TIMERS_REQUIRED = [
    "clawdbot-gmail-triage.timer",
    "clawdbot-newsletter-master.timer",
]

# Canon authority split (fixed).
SYSTEMD_INTENTS = {"gmail-plumber-daily", "newsletter-master-weekly"}
CRON_INTENTS = {"morning-brief", "end-of-day-summary", "weekly-top3"}


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # FAIL | WARN | INFO
    message: str
    evidence: Dict[str, Any]


def _run(cmd: List[str], *, timeout_s: int = 20) -> Tuple[int, str, str]:
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_s)
    return proc.returncode, proc.stdout, proc.stderr


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except PermissionError:
        pass


def _atomic_write(path: Path, text: str, *, mode: int = 0o600) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, mode)
    except PermissionError:
        pass
    os.replace(tmp, path)


def _safe_write_json(path: Path, obj: Any) -> None:
    _atomic_write(path, json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True) + "\n")


def _list_systemd_timers() -> Dict[str, Any]:
    rc, out, err = _run(["systemctl", "--user", "list-timers", "--all", "--no-pager"], timeout_s=20)
    return {"rc": rc, "out": out, "err": err}


def _load_cron_jobs() -> Dict[str, Any]:
    data: Dict[str, Any] = {"path": str(CRON_JOBS_JSON), "exists": CRON_JOBS_JSON.exists(), "jobs": []}
    if not CRON_JOBS_JSON.exists():
        return data
    try:
        obj = _read_json(CRON_JOBS_JSON)
    except Exception as exc:
        data["error"] = f"parse_failed: {exc}"
        return data
    jobs = obj.get("jobs") if isinstance(obj, dict) else None
    if not isinstance(jobs, list):
        data["error"] = "jobs_missing_or_invalid"
        return data
    data["jobs"] = jobs
    return data


def _enabled_cron_names(cron: Dict[str, Any]) -> Dict[str, Any]:
    enabled: List[str] = []
    for row in cron.get("jobs") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        if bool(row.get("enabled")):
            enabled.append(name)
    enabled.sort()
    return {"enabled": enabled}


def main() -> int:
    findings: List[Finding] = []

    # Basic path existence checks.
    for p, code in [
        (GMAIL_TRIAGE_CONFIG, "path.gmail_triage_config"),
        (CRON_JOBS_JSON, "path.cron_jobs_json"),
        (WORKFLOWS_SOT, "path.workflows_sot"),
        (TAG_MAP, "path.tag_map"),
    ]:
        if not p.exists():
            findings.append(Finding(code=code, severity="FAIL", message=f"Missing required path: {p}", evidence={}))

    # Legacy workflows are expected to exist but must be treated non-canonical.
    if WORKFLOWS_LEGACY.exists():
        findings.append(
            Finding(
                code="path.workflows_legacy_present",
                severity="INFO",
                message="Legacy workflows directory exists (must remain non-canonical).",
                evidence={"path": str(WORKFLOWS_LEGACY)},
            )
        )

    # Parse tag map JSON.
    if TAG_MAP.exists():
        try:
            _read_json(TAG_MAP)
        except Exception as exc:
            findings.append(
                Finding(
                    code="tag_map.invalid_json",
                    severity="FAIL",
                    message="tag_map.json is not valid JSON.",
                    evidence={"path": str(TAG_MAP), "error": str(exc)},
                )
            )

    # Scheduler drift: systemd timers presence + cron duplicates enabled.
    timers = _list_systemd_timers()
    if timers["rc"] != 0:
        findings.append(
            Finding(
                code="systemd.list_timers_failed",
                severity="FAIL",
                message="Unable to list systemd user timers.",
                evidence={"rc": timers["rc"], "err": timers["err"][:500]},
            )
        )
    else:
        for unit in SYSTEMD_TIMERS_REQUIRED:
            if unit not in timers["out"]:
                findings.append(
                    Finding(
                        code="systemd.timer_missing",
                        severity="FAIL",
                        message=f"Required systemd timer not present in list-timers output: {unit}",
                        evidence={"unit": unit},
                    )
                )

    cron = _load_cron_jobs()
    enabled = _enabled_cron_names(cron)["enabled"]

    # Disallowed cron duplicates (systemd intents) must be disabled.
    for name in sorted(SYSTEMD_INTENTS):
        if name in enabled:
            findings.append(
                Finding(
                    code="scheduler.drift.cron_duplicate_enabled",
                    severity="FAIL",
                    message=f"Cron job enabled but intent is systemd-authoritative: {name}",
                    evidence={"cron_job": name},
                )
            )

    # Basic canon expectation: cron intents should exist in ledger (enabled/disabled depends on PRD phase).
    # We do not fail if missing, but we report it.
    known_names = {str(row.get("name") or "").strip() for row in (cron.get("jobs") or []) if isinstance(row, dict)}
    for name in sorted(CRON_INTENTS):
        if name not in known_names:
            findings.append(
                Finding(
                    code="cron.intent_missing",
                    severity="WARN",
                    message=f"Cron intent missing from ledger (expected by canon, may be pending activation): {name}",
                    evidence={"cron_job": name},
                )
            )

    # Artifacts: gmail-triage ledger presence.
    reports_dir = JARVIS_DATA / "gmail-triage" / "reports"
    if reports_dir.exists():
        any_reports = bool(list(reports_dir.glob("gmail-triage-*.json")))
        if not any_reports:
            findings.append(
                Finding(
                    code="artifacts.gmail_triage_reports_empty",
                    severity="WARN",
                    message="No gmail-triage ledger reports found.",
                    evidence={"path": str(reports_dir)},
                )
            )
    else:
        findings.append(
            Finding(
                code="artifacts.gmail_triage_reports_missing",
                severity="FAIL",
                message="Missing gmail-triage reports directory.",
                evidence={"path": str(reports_dir)},
            )
        )

    # Weekly newsletter archive invariants (layout only).
    archive_root = JARVIS_DATA / "archive" / "newsletter-weekly"
    latest_link = JARVIS_DATA / "newsletter-weekly" / "latest"
    if not archive_root.exists():
        findings.append(
            Finding(
                code="artifacts.newsletter_archive_missing",
                severity="WARN",
                message="Newsletter weekly archive root missing (expected by canon).",
                evidence={"path": str(archive_root)},
            )
        )
    if latest_link.exists() and not latest_link.is_symlink():
        findings.append(
            Finding(
                code="artifacts.newsletter_latest_not_symlink",
                severity="WARN",
                message="newsletter-weekly/latest exists but is not a symlink.",
                evidence={"path": str(latest_link)},
            )
        )
    if not latest_link.exists():
        findings.append(
            Finding(
                code="artifacts.newsletter_latest_missing",
                severity="WARN",
                message="newsletter-weekly/latest symlink is missing (created only on PASS by pipeline).",
                evidence={"path": str(latest_link)},
            )
        )

    # Build report output.
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conflicts = {
        "ts": ts,
        "enabled_cron_jobs": enabled,
        "systemd_timers_required": SYSTEMD_TIMERS_REQUIRED,
        "systemd_intents": sorted(SYSTEMD_INTENTS),
        "cron_intents": sorted(CRON_INTENTS),
        "findings": [f.__dict__ for f in findings],
    }

    # Human-readable report.
    n_fail = sum(1 for f in findings if f.severity == "FAIL")
    n_warn = sum(1 for f in findings if f.severity == "WARN")
    status = "PASS" if n_fail == 0 else "FAIL"

    lines: List[str] = []
    lines.append("# Canon Check Report")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{ts}`")
    lines.append(f"- Status: **{status}**")
    lines.append(f"- Failures: `{n_fail}`")
    lines.append(f"- Warnings: `{n_warn}`")
    lines.append("")
    lines.append("## Findings")
    if not findings:
        lines.append("- None.")
    else:
        for f in findings:
            lines.append(f"- `{f.severity}` `{f.code}`: {f.message}")
    lines.append("")
    lines.append("## Evidence Paths")
    lines.append(f"- Cron ledger: `{CRON_JOBS_JSON}`")
    lines.append(f"- Gmail triage config: `{GMAIL_TRIAGE_CONFIG}`")
    lines.append(f"- Workflows SoT: `{WORKFLOWS_SOT}`")
    lines.append(f"- Tag map: `{TAG_MAP}`")
    lines.append(f"- Audit output: `{LATEST_DIR}`")
    lines.append("")

    _ensure_dir(LATEST_DIR)
    _atomic_write(LATEST_DIR / "canon_check_report.md", "\n".join(lines) + "\n")
    _safe_write_json(LATEST_DIR / "conflicts.json", conflicts)

    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

