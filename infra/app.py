#!/usr/bin/env python3
"""Bamboozled's own CDK app. Imports nothing from any other project. Configuration: infra/bamboozled.env (git-ignored)."""
import os
from pathlib import Path

import aws_cdk as cdk

from bamboozled_infra.config import Cfg
from bamboozled_infra.stacks.data_stack import DataStack
from bamboozled_infra.stacks.edge_stack import EdgeStack
from bamboozled_infra.stacks.host_stack import HostStack
from bamboozled_infra.stacks.monitoring_stack import MonitoringStack

HERE = Path(__file__).resolve().parent
REPO_ROOT = str(HERE.parent)


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())          # the real environment wins


def build(cfg: Cfg, app: cdk.App) -> dict:
    env = cdk.Environment(account=cfg.account, region=cfg.region)
    n = cfg.env_name
    data = DataStack(app, f"BamboozledData-{n}", cfg, REPO_ROOT, env=env)
    edge = EdgeStack(app, f"BamboozledEdge-{n}", cfg, env=env)
    host = HostStack(app, f"BamboozledHost-{n}", cfg, data, edge, env=env)
    mon = MonitoringStack(app, f"BamboozledMonitoring-{n}", cfg, env=env)
    return {"data": data, "edge": edge, "host": host, "monitoring": mon}


if __name__ == "__main__":
    load_env_file(HERE / "bamboozled.env")
    app = cdk.App()
    build(Cfg.from_env(), app)
    app.synth()
