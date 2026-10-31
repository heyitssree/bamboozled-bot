#!/bin/bash
# scripts/put-secrets.sh [env]   Silent prompts -> SSM SecureString under /bamboozled/<env>/. Values never echo, never go in
# arguments of a visible command line history (they are passed on stdin through a file descriptor), and are never read back.
set -euo pipefail
ENVN="${1:-prod}"; P="/bamboozled/$ENVN"
put() {   # put <name> <prompt>
  local v; read -r -s -p "$2: " v; echo
  [ -n "$v" ] || { echo "  skipped $1"; return 0; }
  aws ssm put-parameter --name "$P/$1" --type SecureString --overwrite --value "file:///dev/stdin" <<<"$v" >/dev/null
  echo "  stored $P/$1"
}
put discord_token "Bot token"
put discord_client_secret "OAuth client secret"
put discord_application_id "Application id (public)"
put discord_public_key "Public key"
put origin_verify "Origin verify value (must equal BAMBOOZLED_ORIGIN_VERIFY in infra/bamboozled.env)"
