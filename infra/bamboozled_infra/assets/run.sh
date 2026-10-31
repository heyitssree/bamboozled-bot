#!/bin/bash
# /opt/bamboozled/run.sh (started by bamboozled.service; Restart=always)
set -euo pipefail
source /opt/bamboozled/env
ssm() { aws ssm get-parameter --name "$1" --query Parameter.Value --output text 2>/dev/null || echo "${2:-}"; }
[ "$(ssm "$BAMBOOZLED_SSM_PREFIX/run_enabled" false)" = "true" ] || { echo "run_enabled != true; idling"; exec sleep infinity; }
docker rm -f bamboozled 2>/dev/null || true
# --oom-score-adj 500: if the host runs short of memory, this container is killed before anything else on the VM.
# No --network flag (default bridge); no volume, port or variable is shared with any other container.
exec docker run --name bamboozled --rm --env-file /opt/bamboozled/env \
  -v /var/lib/bamboozled:/app/data -p "$PORT":8480 \
  --memory 400m --memory-swap 400m --cpus 1.0 --oom-score-adj 500 \
  --log-driver=awslogs --log-opt awslogs-group="$LOG_GROUP" --log-opt awslogs-region="$AWS_REGION" \
  "$(cat /opt/bamboozled/image)"
