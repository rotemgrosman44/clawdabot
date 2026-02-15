#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

from canon_guard_lib import atomic_write_json, sha256_file, utc_now_iso


SOT_DIR = Path("/home/rotemgrosman/clawd/workflows")
MIRROR_DIR = Path("/home/rotemgrosman/jarvis-stack/jarvis-data/workflows")
MIRROR_META = MIRROR_DIR / "mirror_meta.json"


def _copy_yaml_files(src: Path, dst: Path) -> List[Path]:
    dst.mkdir(parents=True, exist_ok=True)
    copied: List[Path] = []
    for p in sorted(src.glob("*.yaml")):
        if not p.is_file():
            continue
        out = dst / p.name
        shutil.copy2(p, out)
        copied.append(out)
    return copied


def run() -> Dict[str, Any]:
    if not SOT_DIR.exists():
        raise RuntimeError(f"sot_missing:{SOT_DIR}")

    copied = _copy_yaml_files(SOT_DIR, MIRROR_DIR)

    files = []
    for p in copied:
        files.append({"name": p.name, "sha256": sha256_file(p)})

    meta = {
        "kind": "workflow_mirror_meta",
        "generated_at": utc_now_iso(),
        "generated_from": {
            "sot_dir": str(SOT_DIR),
            "sot_files_count": len(list(SOT_DIR.glob('*.yaml'))),
        },
        "mirror_dir": str(MIRROR_DIR),
        "files_count": len(files),
        "files": sorted(files, key=lambda x: x["name"]),
    }

    atomic_write_json(MIRROR_META, meta)
    return meta


if __name__ == "__main__":
    run()
    raise SystemExit(0)

