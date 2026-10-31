"""Typed configuration from the environment (infra/bamboozled.env is loaded into it by app.py)."""
from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Cfg:
    env_name: str
    account: str
    region: str
    host_tag_key: str
    host_tag_value: str
    host_role_name: str
    host_vpc_id: str
    host_subnet_id: str
    host_az: str
    cloudfront_prefix_list_id: str
    alert_email: str
    budget_usd: float
    discord_app_id: str
    origin_verify_value: str
    platform: str = "linux/arm64"

    @classmethod
    def from_env(cls, e=None) -> "Cfg":
        e = os.environ if e is None else e
        names = {
            "env_name": "BAMBOOZLED_ENV_NAME", "account": "CDK_DEFAULT_ACCOUNT", "region": "CDK_DEFAULT_REGION",
            "host_tag_key": "BAMBOOZLED_HOST_TAG_KEY", "host_tag_value": "BAMBOOZLED_HOST_TAG_VALUE",
            "host_role_name": "BAMBOOZLED_HOST_ROLE_NAME", "host_vpc_id": "BAMBOOZLED_HOST_VPC_ID",
            "host_subnet_id": "BAMBOOZLED_HOST_SUBNET_ID", "host_az": "BAMBOOZLED_HOST_AZ",
            "cloudfront_prefix_list_id": "BAMBOOZLED_CLOUDFRONT_PREFIX_LIST_ID", "alert_email": "BAMBOOZLED_ALERT_EMAIL",
            "discord_app_id": "BAMBOOZLED_DISCORD_APP_ID", "origin_verify_value": "BAMBOOZLED_ORIGIN_VERIFY",
        }
        missing = [v for v in names.values() if not e.get(v)]
        if missing:
            raise ConfigError("missing in infra/bamboozled.env or the environment: " + ", ".join(missing))
        values = {k: e[v] for k, v in names.items()}
        values["budget_usd"] = float(e.get("BAMBOOZLED_BUDGET_USD", "10"))
        values["platform"] = e.get("BAMBOOZLED_PLATFORM", "linux/arm64")
        if len(values["origin_verify_value"]) < 24:
            raise ConfigError("BAMBOOZLED_ORIGIN_VERIFY must be at least 24 characters (openssl rand -hex 24)")
        return cls(**values)

    @property
    def prefix(self) -> str:
        return f"/bamboozled/{self.env_name}"
