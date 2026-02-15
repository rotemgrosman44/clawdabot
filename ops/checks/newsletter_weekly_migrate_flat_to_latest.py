#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List

from canon_guard_lib import utc_now_ts


JARVIS_DATA = Path("/home/rotemgrosman/jarvis-stack/jarvis-data")
LEGACY_DIR = JARVIS_DATA / "newsletter-weekly"
LATEST_LINK = LEGACY_DIR / "latest"
BACKUP_ROOT = JARVIS_DATA / "backups"


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists() or path.is_symlink():
            path.unlink()
    except Exception:
        pass


def run() -> None:
    if not LATEST_LINK.exists() or not LATEST_LINK.is_symlink():
        raise RuntimeError(f"latest_missing_or_not_symlink:{LATEST_LINK}")

    latest_target = LATEST_LINK.resolve()
    if not latest_target.exists() or not latest_target.is_dir():
        raise RuntimeError(f"latest_target_invalid:{latest_target}")

    # Back up real flat files before replacing with symlinks.
    ts = utc_now_ts()
    backup_dir = BACKUP_ROOT / f"newsletter-weekly-flat-{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    mapping = {
        "message.txt": latest_target / "telegram_message.txt",
        "signals.json": latest_target / "signals.json",
        "report.json": latest_target / "report.json",
        "report.md": latest_target / "report.md",
    }

    for name, target in mapping.items():
        p = LEGACY_DIR / name
        if p.exists() and not p.is_symlink():
            shutil.move(str(p), str(backup_dir / name))
        _safe_unlink(p)
        # Create a relative-ish symlink when possible.
        rel = os.path.relpath(str(target), str(LEGACY_DIR))
        os.symlink(rel, str(p))


if __name__ == "__main__":
    run()
    raise SystemExit(0)

