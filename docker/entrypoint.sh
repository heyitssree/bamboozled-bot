#!/bin/sh
# Restore the databases when missing (from the replica, else a seeded copy in s3://<bucket>/seed/), then run the app
# under Litestream so it is replicated. Without LITESTREAM_ENABLED=1 the app just runs.
set -eu
if [ "${LITESTREAM_ENABLED:-0}" = "1" ]; then
  for db in bamboozled privacy; do
    f="/app/data/$db.db"
    [ -f "$f" ] || litestream restore -if-replica-exists -config /etc/litestream.yml "$f" || true
    [ -f "$f" ] || { [ -z "${BAMBOOZLED_BUCKET:-}" ] || python -c "
import boto3, os, sys
try: boto3.client('s3').download_file(os.environ['BAMBOOZLED_BUCKET'], 'seed/$db.db', '$f')
except Exception: sys.exit(0)" ; }
  done
  exec litestream replicate -config /etc/litestream.yml -exec "python -m bamboozled"
fi
exec python -m bamboozled
