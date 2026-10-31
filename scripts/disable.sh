#!/bin/bash
# scripts/disable.sh [env]   Stop serving: the unit idles at its next restart (the container is stopped by:
# systemctl restart bamboozled on the host).
set -euo pipefail
ENVN="${1:-prod}"
aws ssm put-parameter --name "/bamboozled/$ENVN/run_enabled" --type String --overwrite --value false >/dev/null
echo "run_enabled=false for $ENVN"
