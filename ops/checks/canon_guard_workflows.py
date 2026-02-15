#!/usr/bin/env python3
from __future__ import annotations

import sys
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canon_guard_lib import (
    atomic_write_json,
    atomic_write_text,
    md_codeblock,
    md_section,
    sha256_file,
    status_rollup,
    utc_now_iso,
)


SOT_DIR = Path("/home/rotemgrosman/clawd/workflows")
MIRROR_DIR = Path("/home/rotemgrosman/jarvis-stack/jarvis-data/workflows")
MIRROR_META = MIRROR_DIR / "mirror_meta.json"
YAML_VALIDATOR = Path(__file__).resolve().parent / "validate_workflow_yaml.cjs"


def _hash_dir(root: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not root.exists():
        return out
    for p in sorted(root.glob("*.yaml")):
        if p.is_file():
            out[p.name] = sha256_file(p)
    return out


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_yaml(path: Path) -> Dict[str, Any]:
    """
    Validate YAML by delegating to Node (repo already depends on `yaml`).
    Also extracts a top-level `id` field (if present) for duplicate-ID detection.
    """
    if not YAML_VALIDATOR.exists():
        return {"ok": False, "error": "missing_yaml_validator", "id": ""}
    cmd = ["node", str(YAML_VALIDATOR), str(path)]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=10)
    except Exception as exc:
        return {"ok": False, "error": f"node_exec_failed:{exc}", "id": ""}
    if proc.returncode != 0:
        return {"ok": False, "error": f"node_rc={proc.returncode}", "id": ""}
    try:
        data = json.loads(proc.stdout)
    except Exception:
        return {"ok": False, "error": "node_json_parse_failed", "id": ""}
    if not isinstance(data, dict):
        return {"ok": False, "error": "node_json_not_object", "id": ""}
    ok = bool(data.get("ok"))
    err = str(data.get("error") or "")
    wid = str(data.get("id") or "")
    return {"ok": ok, "error": err, "id": wid}


def run(out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    sot = _hash_dir(SOT_DIR)
    mirror = _hash_dir(MIRROR_DIR)

    missing_in_mirror = sorted([n for n in sot.keys() if n not in mirror])
    missing_in_sot = sorted([n for n in mirror.keys() if n not in sot])
    drifted = sorted([n for n in sot.keys() if n in mirror and sot[n] != mirror[n]])

    checks: List[Dict[str, Any]] = []

    checks.append(
        {
            "id": "workflows_sot_exists",
            "status": "PASS" if SOT_DIR.exists() else "FAIL",
            "detail": str(SOT_DIR),
        }
    )
    checks.append(
        {
            "id": "workflows_sot_nonempty",
            "status": "PASS" if len(sot) > 0 else ("FAIL" if SOT_DIR.exists() else "FAIL"),
            "detail": f"count={len(sot)}",
        }
    )

    # Validate YAML in SoT (internal consistency). Any parse error is FAIL.
    validation: Dict[str, Dict[str, Any]] = {}
    ids: List[str] = []
    yaml_ok = True
    for name in sorted(sot.keys()):
        p = SOT_DIR / name
        v = _validate_yaml(p)
        validation[name] = v
        if not v.get("ok"):
            yaml_ok = False
        wid = str(v.get("id") or "").strip()
        if wid and wid != "none":
            ids.append(wid)

    checks.append(
        {
            "id": "workflows_sot_yaml_parse_ok",
            "status": "PASS" if yaml_ok else "FAIL",
            "detail": f"validated={len(validation)}",
        }
    )

    dup_ids = sorted([x for x in set(ids) if ids.count(x) > 1])
    checks.append(
        {
            "id": "workflows_sot_duplicate_ids",
            "status": "FAIL" if dup_ids else "PASS",
            "detail": f"ids_detected={len(ids)} dup={len(dup_ids)}",
            "dup_ids": dup_ids,
        }
    )

    # Mirror drift policy:
    # - PASS if mirror identical to SoT, OR mirror differs but has generation metadata.
    # - WARN only if mirror differs and generation metadata is missing.
    # - PASS if mirror directory does not exist (optional).
    mirror_meta: Dict[str, Any] = {}
    meta_ok = False
    if MIRROR_META.exists():
        try:
            mirror_meta = _read_json(MIRROR_META)
            meta_ok = isinstance(mirror_meta, dict) and isinstance(mirror_meta.get("generated_from"), dict)
        except Exception:
            mirror_meta = {}
            meta_ok = False

    mirror_diff = bool(missing_in_mirror or missing_in_sot or drifted)
    if not MIRROR_DIR.exists():
        mirror_status = "PASS"
    elif not mirror_diff:
        mirror_status = "PASS"
    else:
        mirror_status = "PASS" if meta_ok else "WARN"

    checks.append(
        {
            "id": "workflows_mirror_drift",
            "status": mirror_status,
            "detail": f"mirror_exists={MIRROR_DIR.exists()} meta_ok={meta_ok} drifted={len(drifted)} missing_in_mirror={len(missing_in_mirror)} missing_in_sot={len(missing_in_sot)}",
            "drifted": drifted,
            "missing_in_mirror": missing_in_mirror,
            "missing_in_sot": missing_in_sot,
            "mirror_meta_path": str(MIRROR_META),
            "mirror_meta_present": MIRROR_META.exists(),
        }
    )

    overall = status_rollup([c["status"] for c in checks])

    report = {
        "kind": "canon_guard_workflows",
        "generated_at": utc_now_iso(),
        "overall_status": overall,
        "sot_dir": str(SOT_DIR),
        "mirror_dir": str(MIRROR_DIR),
        "sot_hashes": sot,
        "mirror_hashes": mirror,
        "missing_in_mirror": missing_in_mirror,
        "missing_in_sot": missing_in_sot,
        "drifted": drifted,
        "mirror_meta": mirror_meta,
        "sot_validation": validation,
        "checks": checks,
    }

    md = "# Canon Guard: Workflows\n\n"
    md += md_section("Overall", f"- status: `{overall}`\n- generated_at: `{report['generated_at']}`")
    md += md_section(
        "SoT",
        "\n".join([f"- dir: `{SOT_DIR}`", f"- yaml count: `{len(sot)}`"]),
    )
    md += md_section(
        "Mirror Drift",
        "\n".join(
            [
                f"- mirror dir: `{MIRROR_DIR}` exists={MIRROR_DIR.exists()}",
                f"- mirror meta: `{MIRROR_META}` present={MIRROR_META.exists()}",
                f"- drifted: `{len(drifted)}`",
                f"- missing_in_mirror: `{len(missing_in_mirror)}`",
                f"- missing_in_sot: `{len(missing_in_sot)}`",
            ]
        ),
    )
    md += md_section("Checks", md_codeblock("\n".join([f"{c['status']}\t{c['id']}\t{c.get('detail','')}" for c in checks])))

    atomic_write_json(out_dir / "workflows_sot_report.json", report)
    atomic_write_text(out_dir / "workflows_sot_report.md", md)

    # Save hashes as evidence-friendly text.
    atomic_write_text(out_dir / "workflows_sot_sha256.txt", "\n".join([f"{h}  {n}" for n, h in sorted(sot.items())]) + "\n")
    atomic_write_text(out_dir / "workflows_mirror_sha256.txt", "\n".join([f"{h}  {n}" for n, h in sorted(mirror.items())]) + "\n")
    atomic_write_json(out_dir / "workflows_sot_validation.json", validation)

    return report


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="", help="Output directory (default: current working dir)")
    args = ap.parse_args()
    out = Path(args.out_dir) if args.out_dir else Path.cwd()
    rep = run(out)
    raise SystemExit(0 if rep.get("overall_status") in ("PASS", "WARN") else 2)
