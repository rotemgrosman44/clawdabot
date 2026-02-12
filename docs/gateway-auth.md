# Gateway Auth Token ("Toke API") Mapping

This gateway uses a shared token to authorize clients (CLI, TUI, Control UI, remote nodes) connecting to the gateway server.

## Canonical Key Names

The gateway auth token is resolved from:

1. `gateway.auth.token` in the active config file, OR
2. `CLAWDBOT_GATEWAY_TOKEN` from the process environment.

Evidence (code):

- `dist/gateway/auth.js` resolves:
  - `token = authConfig.token ?? env.CLAWDBOT_GATEWAY_TOKEN`
  - errors: `set gateway.auth.token or CLAWDBOT_GATEWAY_TOKEN`

## What It Secures

When gateway auth mode is `token`, inbound gateway connect attempts must include the matching token.

Evidence (code):

- `dist/gateway/auth.js` (`authorizeGatewayConnect`):
  - `token_missing_config`, `token_missing`, `token_mismatch`

Related user-facing hints:

- `dist/gateway/server-runtime-config.js` refuses non-loopback binds without auth configured.
- `dist/gateway/server/ws-connection/message-handler.js` emits unauthorized hints on mismatch.

## Reproduction (Safe)

1. Confirm the service has the token set (do not print the value):
   - `systemctl --user show clawdbot-gateway.service -p Environment --no-pager | tr " " "\\n" | rg "^CLAWDBOT_GATEWAY_TOKEN=" | sed -E "s/=.*$/=<set>/"`

2. Attempt a gateway operation from a client with a mismatched token:
   - Expected: an unauthorized / token mismatch error (reason contains `token_mismatch`).

Notes:

- In operator language, "Toke API" maps to `CLAWDBOT_GATEWAY_TOKEN` (or `gateway.auth.token` if configured in JSON).
- Keep the token in systemd drop-ins / environment; do not paste it into logs or chat.

