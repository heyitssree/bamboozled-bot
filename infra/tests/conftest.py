import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bamboozled_infra.config import Cfg  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return Cfg(env_name="test", account="111122223333", region="ap-southeast-2", host_tag_key="HostGroup", host_tag_value="shared",
               host_role_name="HostRole", host_vpc_id="vpc-0abc", host_subnet_id="subnet-0abc", host_az="ap-southeast-2a",
               cloudfront_prefix_list_id="pl-0abc", alert_email="owner@example.com", budget_usd=10, discord_app_id="1234",
               origin_verify_value="x" * 32)


@pytest.fixture(scope="session")
def stacks(cfg, tmp_path_factory):
    import aws_cdk as cdk

    from app import build
    app = cdk.App(outdir=str(tmp_path_factory.mktemp("cdkout")))
    return build(cfg, app)


@pytest.fixture(scope="session")
def templates(stacks):
    from aws_cdk.assertions import Template
    return {k: Template.from_stack(v) for k, v in stacks.items()}
