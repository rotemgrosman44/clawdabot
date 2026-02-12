# Google Workspace OAuth (gogcli) Verification And Remediation

This stack uses `gog` (gogcli) as the Google OAuth + token/keyring mechanism.

## Source Of Truth

- OAuth client:
  - `/home/rotemgrosman/.config/gogcli/oauth-client.json` (mode 600)
- Stored credentials:
  - `/home/rotemgrosman/.config/gogcli/credentials.json` (mode 600)
- Keyring env (loaded by systemd):
  - `/home/rotemgrosman/.config/gogcli/keyring.env`

The Gateway process must have the keyring env so scheduled runs can decrypt tokens.

Verify gateway has the env (presence only, no secrets):

```bash
pid=$(systemctl --user show clawdbot-gateway.service -p MainPID --value)
tr "\0" "\n" < /proc/$pid/environ | rg "^GOG_KEYRING_(BACKEND|PASSWORD)=" | sed -E 's/=.*$/=<set>/'
```

## Current OAuth Scopes (Inventory)

Generate an audited scope matrix artifact:

```bash
cd /home/rotemgrosman/jarvis-stack/jarvis/clawdbot
set -a
. /home/rotemgrosman/.config/gogcli/keyring.env
set +a
python3 scripts/gog_scope_matrix.py --account grosmanrotem@gmail.com --drive-scope file
```

Artifact:

`/home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/scope_matrix.json`

## Minimum Required Scopes (Newsletter Master + Email-Triage)

Gmail (already granted):

- `https://www.googleapis.com/auth/gmail.modify`
- `https://www.googleapis.com/auth/gmail.settings.basic`
- `https://www.googleapis.com/auth/gmail.settings.sharing`

Drive (recommended least-privilege for “files created by the app”):

- `https://www.googleapis.com/auth/drive.file`

Docs:

- `https://www.googleapis.com/auth/documents`
- plus the selected Drive scope (`drive.file`)

Optional (only if required by automation):

- Sheets: `https://www.googleapis.com/auth/spreadsheets` + Drive scope
- Calendar: `https://www.googleapis.com/auth/calendar`

## Diagnosis: “Google Drive credentials missing”

This symptom typically means one of:

1. Missing scopes in the stored refresh token (most common).
2. The runtime environment can’t decrypt tokens (missing `GOG_KEYRING_PASSWORD` in the job runtime).
3. Wrong account selected (`--account` mismatch).

The scope matrix artifact reports missing scopes explicitly under:

- `.requirements.missing_scopes.drive`
- `.requirements.missing_scopes.docs`

## Remediation (Add Scopes Safely)

Re-authorize with only the required services (adds Drive + Docs while keeping Gmail):

```bash
set -a
. /home/rotemgrosman/.config/gogcli/keyring.env
set +a
gog auth add grosmanrotem@gmail.com --services gmail,drive,docs --drive-scope file --manual --force-consent
```

Notes:

- This is interactive. `gog` will show a URL. Complete consent in a browser.
- For `--manual`, you paste the final redirect URL back into the CLI prompt.
- Do not paste redirect URLs, auth codes, refresh tokens, or client secrets into chat or docs.

Verify after re-auth:

```bash
cd /home/rotemgrosman/jarvis-stack/jarvis/clawdbot
set -a
. /home/rotemgrosman/.config/gogcli/keyring.env
set +a
python3 scripts/gog_scope_matrix.py --account grosmanrotem@gmail.com --drive-scope file
jq -r '{missing:.requirements.missing_scopes, probes:(.probes|map({service,ok,reason}))}' \
  /home/rotemgrosman/jarvis-stack/jarvis-data/gmail-triage/scope_matrix.json
```

## Smoke Test (Write Verification)

After scopes are present, run the workspace smoke test script (creates a folder + doc):

`/home/rotemgrosman/jarvis-stack/jarvis/clawdbot/scripts/google_workspace_smoke.py`

(See script help for flags; default mode is read-only.)

