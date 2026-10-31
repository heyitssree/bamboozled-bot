#!/bin/bash
# scripts/enable.sh [env]   Start serving: the unit stops idling at its next restart (run: systemctl restart bamboozled on the host,
# or wait for the next association run).
set -euo pipefail
ENVN="${1:-prod}"
aws ssm put-parameter --name "/bamboozled/$ENVN/run_enabled" --type String --overwrite --value true >/dev/null
echo "run_enabled=true for $ENVN"
