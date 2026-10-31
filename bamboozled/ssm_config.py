"""Production configuration: copy every SSM parameter under BAMBOOZLED_SSM_PREFIX into the environment before Config is read.

`/bamboozled/prod/discord_token` becomes DISCORD_TOKEN. A variable that is already set wins. SecureString values are
decrypted here and never logged. Infrastructure keys are not configuration for the process and are skipped.
"""
from __future__ import annotations

import logging
import os
from typing import MutableMapping, Optional

log = logging.getLogger("bamboozled.ssm")
INFRA_KEYS = {"image_uri", "run_enabled", "eni_id"}


def load_ssm_into_environ(environ: Optional[MutableMapping[str, str]] = None, client=None) -> int:
    """Returns how many variables were set. Does nothing (returns 0) when no prefix is configured."""
    env = os.environ if environ is None else environ
    prefix = env.get("BAMBOOZLED_SSM_PREFIX", "").rstrip("/")
    if not prefix:
        return 0
    if client is None:
        import boto3
        client = boto3.client("ssm", region_name=env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION"))
    set_count, token = 0, None
    while True:
        kwargs = {"Path": prefix, "WithDecryption": True, **({"NextToken": token} if token else {})}
        page = client.get_parameters_by_path(**kwargs)
        for p in page["Parameters"]:
            name = p["Name"].rsplit("/", 1)[-1]
            if name in INFRA_KEYS or p["Name"].count("/") != prefix.count("/") + 1:
                continue
            key = name.upper()
            if key not in env:
                env[key] = p["Value"]
                set_count += 1
        token = page.get("NextToken")
        if not token:
            break
    log.info("Loaded %d setting(s) from SSM under %s", set_count, prefix)
    return set_count
