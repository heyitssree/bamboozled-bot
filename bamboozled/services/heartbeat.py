"""Every 5 minutes: PutMetricData Bamboozled/Heartbeat (dimension Env). The alarm fires after 15 minutes without one."""
from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger("bamboozled.heartbeat")
INTERVAL_S = 300


def put_heartbeat(env_name: str, client=None) -> None:
    if client is None:
        import boto3
        client = boto3.client("cloudwatch")
    client.put_metric_data(Namespace="Bamboozled", MetricData=[
        {"MetricName": "Heartbeat", "Dimensions": [{"Name": "Env", "Value": env_name}], "Value": 1, "Unit": "Count"}])


async def run_heartbeat(env_name: str, put=put_heartbeat, interval_s: float = INTERVAL_S) -> None:
    while True:
        try:
            await asyncio.to_thread(put, env_name)
        except Exception as exc:                                  # a missed beat is an alarm, not a crash
            log.warning("heartbeat failed: %s", type(exc).__name__)
        await asyncio.sleep(interval_s)


def enabled() -> bool:
    return bool(os.environ.get("BAMBOOZLED_ENV")) and os.environ.get("BAMBOOZLED_ENV") != "test"
