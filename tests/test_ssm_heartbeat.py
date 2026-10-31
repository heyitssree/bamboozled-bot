import asyncio

from bamboozled.services.heartbeat import put_heartbeat, run_heartbeat
from bamboozled.ssm_config import load_ssm_into_environ


class FakeSsm:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get_parameters_by_path(self, **kw):
        self.calls.append(kw)
        return self.pages[len(self.calls) - 1]


def P(name, value="v"):
    return {"Name": f"/bamboozled/prod/{name}", "Value": value}


def test_parameters_become_upper_case_variables_and_existing_ones_win():
    first = [P("discord_token", "t"), P("origin_verify", "o"), P("image_uri"), P("run_enabled"), P("eni_id")]
    second = [P("discord_public_key", "k"), P("deep/nested", "x")]
    ssm = FakeSsm([{"Parameters": first, "NextToken": "n"}, {"Parameters": second}])
    env = {"BAMBOOZLED_SSM_PREFIX": "/bamboozled/prod/", "ORIGIN_VERIFY": "already"}
    assert load_ssm_into_environ(env, ssm) == 2
    assert env["DISCORD_TOKEN"] == "t" and env["DISCORD_PUBLIC_KEY"] == "k" and env["ORIGIN_VERIFY"] == "already"
    assert not {"IMAGE_URI", "RUN_ENABLED", "ENI_ID", "NESTED"} & set(env)
    assert ssm.calls[0]["WithDecryption"] is True and ssm.calls[1]["NextToken"] == "n"


def test_no_prefix_means_no_call():
    assert load_ssm_into_environ({}, client=object()) == 0


def test_heartbeat_metric_shape_and_failures_do_not_stop_the_loop():
    sent = []

    class Cw:
        def put_metric_data(self, **kw):
            sent.append(kw)
    put_heartbeat("prod", Cw())
    assert sent[0]["Namespace"] == "Bamboozled" and sent[0]["MetricData"][0]["Dimensions"] == [{"Name": "Env", "Value": "prod"}]
    calls = []

    def flaky(env):
        calls.append(env)
        raise RuntimeError("no network")

    async def go():
        t = asyncio.create_task(run_heartbeat("prod", flaky, interval_s=0.01))
        await asyncio.sleep(0.1)
        t.cancel()
    asyncio.run(go())
    assert len(calls) >= 3
