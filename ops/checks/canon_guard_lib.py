#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def utc_now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CmdResult:
    cmd: List[str]
    rc: int
    stdout: str
    stderr: str


def run_cmd(cmd: Sequence[str], *, timeout_s: int = 60, env: Optional[Dict[str, str]] = None) -> CmdResult:
    proc = subprocess.run(
        list(cmd),
        text=True,
        capture_output=True,
        timeout=timeout_s,
        env=env,
    )
    return CmdResult(cmd=list(cmd), rc=int(proc.returncode), stdout=proc.stdout, stderr=proc.stderr)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def list_files(root: Path, *, pattern: str = "*") -> List[Path]:
    if not root.exists():
        return []
    return sorted([p for p in root.glob(pattern) if p.is_file()])


def read_text_safe(path: Path, *, max_bytes: int = 256 * 1024) -> str:
    # For governance checks: avoid accidentally slurping huge files.
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[:max_bytes]
    return data.decode("utf-8", errors="replace")


def md_section(title: str, body: str) -> str:
    return f"## {title}\n\n{body.rstrip()}\n"


def md_codeblock(text: str, lang: str = "") -> str:
    return f"```{lang}\n{text.rstrip()}\n```\n"


def status_rollup(statuses: Iterable[str]) -> str:
    order = {"PASS": 0, "WARN": 1, "FAIL": 2}
    worst = "PASS"
    for s in statuses:
        if order.get(s, 2) > order[worst]:
            worst = s
    return worst

