#!/usr/bin/env python3
"""
PRD v13.0 - Create a new weekly Google Doc (Hebrew) and return a stable URL.

Design:
- Creates a *new* Google Doc every week (no overwrite).
- Uses existing gogcli OAuth storage by exporting a refresh token to a temp file
  (contains secrets). The temp file is deleted immediately after use.

Safety:
- Never prints secrets.
- Outputs only doc_id and url to --out-json.

Requires:
- /home/rotemgrosman/.local/bin/gog
- /home/rotemgrosman/.config/gogcli/oauth-client.json (client_id/client_secret)
- gog account authorized for drive + docs scopes

Notes:
- This script performs external API calls (Google). Do not run unless explicitly approved.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple


GOG = "/home/rotemgrosman/.local/bin/gog"
OAUTH_CLIENT = "/home/rotemgrosman/.config/gogcli/oauth-client.json"

DRIVE_API = "https://www.googleapis.com/drive/v3"
DOCS_API = "https://docs.googleapis.com/v1"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _run_gog_export_refresh_token(account: str) -> str:
    # Export to a temp file and read it; do not print.
    fd, out_path = tempfile.mkstemp(prefix="gog_refresh_", suffix=".json")
    os.close(fd)
    os.chmod(out_path, 0o600)
    try:
        cmd = f"{GOG} auth tokens export {account} --out {out_path} --overwrite --no-input --plain"
        rc = os.system(cmd + " >/dev/null 2>/dev/null")
        if rc != 0:
            raise RuntimeError("gog_export_failed")
        data = _read_json(Path(out_path))
        if not isinstance(data, dict):
            raise RuntimeError("gog_export_bad_json")
        tok = data.get("refresh_token")
        if not isinstance(tok, str) or not tok.strip():
            raise RuntimeError("gog_export_missing_refresh_token")
        return tok.strip()
    finally:
        try:
            os.remove(out_path)
        except Exception:
            pass


def _http_json(method: str, url: str, body: Dict[str, Any] | None, headers: Dict[str, str]) -> Dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={**headers, "Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw) if raw else {}


def _http_form(url: str, form: Dict[str, str]) -> Dict[str, Any]:
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw) if raw else {}


def _oauth_access_token(account: str) -> str:
    client = _read_json(Path(OAUTH_CLIENT))
    if not isinstance(client, dict):
        raise RuntimeError("oauth_client_missing")
    cid = client.get("installed", {}).get("client_id") if isinstance(client.get("installed"), dict) else client.get("client_id")
    secret = client.get("installed", {}).get("client_secret") if isinstance(client.get("installed"), dict) else client.get("client_secret")
    if not isinstance(cid, str) or not isinstance(secret, str):
        raise RuntimeError("oauth_client_invalid")

    refresh = _run_gog_export_refresh_token(account)
    tok = _http_form(
        TOKEN_URL,
        {
            "client_id": cid,
            "client_secret": secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        },
    )
    at = tok.get("access_token")
    if not isinstance(at, str) or not at.strip():
        raise RuntimeError("access_token_missing")
    return at.strip()


def _drive_find_or_create_folder(access_token: str, parent_id: str, name: str) -> str:
    # Escape single quotes for Drive query string.
    name_q = name.replace("'", "\\'")
    q = (
        "mimeType='application/vnd.google-apps.folder' "
        f"and name='{name_q}' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    url = f"{DRIVE_API}/files?q={urllib.parse.quote(q)}&fields=files(id,name)"
    out = _http_json("GET", url, None, {"Authorization": f"Bearer {access_token}"})
    files = out.get("files") if isinstance(out.get("files"), list) else []
    if files:
        fid = files[0].get("id")
        if isinstance(fid, str) and fid.strip():
            return fid.strip()

    created = _http_json(
        "POST",
        f"{DRIVE_API}/files?fields=id",
        {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        },
        {"Authorization": f"Bearer {access_token}"},
    )
    fid = created.get("id")
    if not isinstance(fid, str) or not fid.strip():
        raise RuntimeError("drive_mkdir_failed")
    return fid.strip()


def _drive_root_id(access_token: str) -> str:
    about = _http_json(
        "GET",
        f"{DRIVE_API}/about?fields=rootFolderId",
        None,
        {"Authorization": f"Bearer {access_token}"},
    )
    rid = about.get("rootFolderId")
    if not isinstance(rid, str) or not rid.strip():
        raise RuntimeError("drive_root_missing")
    return rid.strip()


def _docs_create(access_token: str, title: str) -> str:
    out = _http_json(
        "POST",
        f"{DOCS_API}/documents",
        {"title": title},
        {"Authorization": f"Bearer {access_token}"},
    )
    doc_id = out.get("documentId")
    if not isinstance(doc_id, str) or not doc_id.strip():
        raise RuntimeError("docs_create_failed")
    return doc_id.strip()


def _drive_move_to_folder(access_token: str, file_id: str, folder_id: str) -> None:
    meta = _http_json(
        "GET",
        f"{DRIVE_API}/files/{file_id}?fields=parents",
        None,
        {"Authorization": f"Bearer {access_token}"},
    )
    parents = meta.get("parents") if isinstance(meta.get("parents"), list) else []
    remove = ",".join([p for p in parents if isinstance(p, str)])
    url = f"{DRIVE_API}/files/{file_id}?addParents={folder_id}&removeParents={urllib.parse.quote(remove)}&fields=id,parents"
    _http_json("PATCH", url, None, {"Authorization": f"Bearer {access_token}"})


def _docs_set_content(access_token: str, doc_id: str, content: str) -> None:
    # Insert at index 1 (after document start).
    _http_json(
        "POST",
        f"{DOCS_API}/documents/{doc_id}:batchUpdate",
        {
            "requests": [
                {"insertText": {"location": {"index": 1}, "text": content}},
            ]
        },
        {"Authorization": f"Bearer {access_token}"},
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--week-id", required=True, help="YYYY-WW")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--in-md", required=True, help="Local report.md path")
    ap.add_argument("--out-json", required=True, help="Output drive_doc.json path")
    args = ap.parse_args()

    access_token = _oauth_access_token(str(args.account))
    root_id = _drive_root_id(access_token)

    # Drive folder convention: Jarvis/Newsletter Weekly/YYYY/MM/week-YYYY-WW/
    jarvis_id = _drive_find_or_create_folder(access_token, root_id, "Jarvis")
    nw_id = _drive_find_or_create_folder(access_token, jarvis_id, "Newsletter Weekly")
    yyyy = str(args.date).split("-")[0]
    mm = str(args.date).split("-")[1]
    y_id = _drive_find_or_create_folder(access_token, nw_id, yyyy)
    m_id = _drive_find_or_create_folder(access_token, y_id, mm)
    w_id = _drive_find_or_create_folder(access_token, m_id, f"week-{args.week_id}")

    title = f"ניוזלטר שבועי - {args.date} (שבוע {args.week_id.split('-')[1]})"
    doc_id = _docs_create(access_token, title)
    _drive_move_to_folder(access_token, doc_id, w_id)

    content = Path(args.in_md).read_text(encoding="utf-8")
    _docs_set_content(access_token, doc_id, content)

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    out = {"doc_id": doc_id, "url": url, "created_at": datetime.now(timezone.utc).isoformat()}
    _atomic_write_json(Path(args.out_json), out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
