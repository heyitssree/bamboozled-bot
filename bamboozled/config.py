"""Process configuration, read from the environment (values from SSM are copied into the environment first)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    env: str = "dev"                          # BAMBOOZLED_ENV: dev | test | prod
    app_id: str = ""                          # DISCORD_APPLICATION_ID
    bot_token: str = ""                       # DISCORD_TOKEN
    client_secret: str = ""                   # DISCORD_CLIENT_SECRET
    public_key: str = ""                      # DISCORD_PUBLIC_KEY (proxy signatures)
    origin_verify: str = ""                   # shared header value CloudFront adds (Phase 8)
    ssm_prefix: str = ""                      # BAMBOOZLED_SSM_PREFIX: configuration comes from SSM
    dev_auth: bool = False                    # BAMBOOZLED_DEV_AUTH: fake Discord for local play and tests
    host: str = "0.0.0.0"
    port: int = 8480
    web_dist: Path = ROOT / "web_dist"
    settings_json: str = ""                  # BAMBOOZLED_SETTINGS_JSON: setting overrides for dev and tests (ignored in prod)

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "Config":
        e = os.environ if environ is None else environ
        cfg = cls(
            env=e.get("BAMBOOZLED_ENV", "dev"), app_id=e.get("DISCORD_APPLICATION_ID", ""),
            bot_token=e.get("DISCORD_TOKEN", ""), client_secret=e.get("DISCORD_CLIENT_SECRET", ""),
            public_key=e.get("DISCORD_PUBLIC_KEY", ""), origin_verify=e.get("ORIGIN_VERIFY", ""),
            ssm_prefix=e.get("BAMBOOZLED_SSM_PREFIX", ""), dev_auth=e.get("BAMBOOZLED_DEV_AUTH") == "1",
            host=e.get("BAMBOOZLED_HOST", "0.0.0.0"), port=int(e.get("BAMBOOZLED_PORT", "8480")),
            web_dist=Path(e.get("BAMBOOZLED_WEB_DIST", str(ROOT / "web_dist"))),
            settings_json=e.get("BAMBOOZLED_SETTINGS_JSON", ""),
        )
        return cfg.checked()

    def setting_overrides(self) -> dict:
        """Parsed BAMBOOZLED_SETTINGS_JSON. Never applied in prod: production settings live in the database."""
        if not self.settings_json or self.env == "prod":
            return {}
        try:
            values = json.loads(self.settings_json)
        except ValueError as exc:
            raise ConfigError(f"BAMBOOZLED_SETTINGS_JSON is not valid JSON: {exc}") from None
        if not isinstance(values, dict):
            raise ConfigError("BAMBOOZLED_SETTINGS_JSON must be a JSON object")
        return values

    def checked(self) -> "Config":
        """Apply the dev-auth guards. Returns the config (dev auth forces loopback) or raises ConfigError."""
        if not self.dev_auth:
            return self
        if self.env == "prod":
            raise ConfigError("BAMBOOZLED_DEV_AUTH is on but BAMBOOZLED_ENV is 'prod': refusing to start")
        if self.ssm_prefix:
            raise ConfigError("BAMBOOZLED_DEV_AUTH is on but SSM-based configuration is active: refusing to start")
        return Config(**{**self.__dict__, "host": "127.0.0.1"})        # dev auth only ever listens on loopback
