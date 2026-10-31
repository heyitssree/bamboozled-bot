"""Dry run of the on-host script against stub commands: idempotent, and the host contract fails loudly."""
import os
import subprocess
import textwrap

import pytest

from bamboozled_infra.install import assemble

STUBS = {
    "curl": 'case "$*" in *api/token*) echo tok;; *instance-id*) echo i-123;; *) echo;; esac',
    "aws": textwrap.dedent('''\
        echo "aws $*" >> "$LOG"
        case "$*" in
          *"ssm get-parameter"*eni_id*) echo eni-1;;
          *"ssm get-parameter"*image_uri*) echo 1.dkr.ecr.ap-southeast-2.amazonaws.com/r:abc;;
          *"ssm get-parameter"*) echo;;
          *attach-network-interface*) touch "$STATE/attached";;
          *describe-network-interfaces*) [ -f "$STATE/attached" ] && echo i-123 || echo None;;
          *get-login-password*) echo pw;;
        esac'''),
    "docker": 'echo "docker $*" >> "$LOG"',
    "systemctl": textwrap.dedent('''\
        echo "systemctl $*" >> "$LOG"
        case "$1" in is-active) [ -f "$STATE/active" ];; restart) touch "$STATE/active";; esac'''),
    "ip": 'echo "ip $*" >> "$LOG"',
}


@pytest.fixture
def sandbox(tmp_path):
    bin_dir, state, root = tmp_path / "bin", tmp_path / "state", tmp_path / "root"
    for d in (bin_dir, state, root):
        d.mkdir()
    for name, body in STUBS.items():
        (bin_dir / name).write_text("#!/bin/bash\n" + body + "\n")
        (bin_dir / name).chmod(0o755)
    script = tmp_path / "install.sh"
    script.write_text(assemble())
    return bin_dir, state, root, script, tmp_path / "calls.log"


def run(sandbox, path_dirs=None):
    bin_dir, state, root, script, log = sandbox
    env = {"PATH": f"{path_dirs or bin_dir}:/usr/bin:/bin", "LOG": str(log), "STATE": str(state), "BAMBOOZLED_ROOT": str(root)}
    return subprocess.run(["bash", str(script), "/bamboozled/test", "test", "ap-southeast-2", "8480", "/bamboozled/test/app", "bkt",
                           "/bamboozled/test/eni_id"], env=env, capture_output=True, text=True, timeout=60)


def calls(sandbox):
    return sandbox[4].read_text().splitlines() if sandbox[4].exists() else []


def test_first_run_installs_and_a_second_run_changes_nothing(sandbox):
    first = run(sandbox)
    assert first.returncode == 0, first.stderr
    c1 = calls(sandbox)
    assert sum("attach-network-interface" in x for x in c1) == 1
    assert sum(x.startswith("docker pull") for x in c1) == 1 and "systemctl restart bamboozled" in c1
    root = sandbox[2]
    env = (root / "opt/bamboozled/env").read_text()
    assert "BAMBOOZLED_SSM_PREFIX=/bamboozled/test" in env and "LITESTREAM_ENABLED=1" in env
    assert oct((root / "opt/bamboozled/env").stat().st_mode)[-3:] == "600"
    assert "ExecStart=/opt/bamboozled/run.sh" in (root / "etc/systemd/system/bamboozled.service").read_text()
    assert "--oom-score-adj 500" in (root / "opt/bamboozled/run.sh").read_text()
    second = run(sandbox)
    assert second.returncode == 0, second.stderr
    c2 = calls(sandbox)[len(c1):]
    assert not [x for x in c2 if "attach-network-interface" in x or x.startswith("docker pull") or "restart" in x or "daemon-reload" in x]


def test_a_missing_requirement_fails_loudly_and_changes_nothing(sandbox):
    bin_dir = sandbox[0]
    (bin_dir / "docker").unlink()
    out = run(sandbox)
    assert out.returncode == 1 and "host lacks docker" in out.stdout
    assert not any(sandbox[2].rglob("*"))
    assert not [x for x in calls(sandbox) if "attach" in x]


def test_no_prune_anywhere():
    assert "prune" not in assemble()
