#!/usr/bin/env bash
set -euo pipefail

orbctl run -m ubuntu -w /home/rotemgrosman bash -lc '
set -e
hostname; uname -a; id; pwd
systemd-analyze --user verify /home/rotemgrosman/.config/systemd/user/clawdbot-gateway.service
systemctl --user is-active clawdbot-gateway.service
curl -fsS -o /dev/null -w "HTTP %{http_code}\\n" http://127.0.0.1:18789/
readlink -f /home/rotemgrosman/.clawdbot/clawdbot.json
sha256sum /home/rotemgrosman/jarvis-stack/jarvis-data/clawdbot.json /home/rotemgrosman/.clawdbot/clawdbot.json
'
