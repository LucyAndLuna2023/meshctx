#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""沙箱硬化策略 (WP7, MCTX-PLAN-2026-0903 P1-4) — Docker 沙箱安全基线。

背景 (002meshctx/002codex 审计 + 2026-09 事件): Artifactory 零日逃逸 / AISI 越权
案例提示 Agent 沙箱需最小权限基线。本模块提供:

1. build_hardened_docker_cmd(image, command, ...) → docker run argv
   硬化基线 (全部默认开启):
   - --network none          默认禁网 (白名单端口才另开, 参数 allow_network=False 显式开启)
   - --read-only             只读 rootfs (仅显式 mount 的 /workspace 可写)
   - --cap-drop ALL         无任何 Linux capability
   - --security-opt no-new-privileges   禁止提权
   - --pids-limit / --memory / --cpus   资源限额
   - --user 65534:65534      非 root 运行
   - 宿主密钥 env 不直传: env 仅经显式白名单 (默认空) 注入
2. classify_escape_risk(script) → SandboxRiskLevel 静态分级 (gate 前置)
   高危模式: docker.sock 挂载 / --privileged / 挂载 /proc|/sys / nsenter/unshare /
   ptrace / chroot / cap_add 等 (Artifactory 型逃逸路径)

宿主 subprocess 直跑 (code_sandbox_v3 默认) 保持不动; 本模块供 docker 化执行路径
与 action_gate 联动使用 — 加法式, 可回滚。
"""
from __future__ import annotations

import logging
import shlex
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger("meshctx.sandbox_policy")

# ── 逃逸风险分级 (静态) ────────────────────────────────────────────────────
_HIGH_RISK_PATTERNS = (
    "/var/run/docker.sock", "/run/docker.sock", "docker.sock",
    "--privileged", "cap_add", "cap-add",
    "nsenter", "unshare", "--mount", "mount -t", "mount /proc",
    "mount /sys", "chroot", "ptrace", "kexec", "modprobe", "insmod",
    "/proc/sys", "/sys/kernel", "cgroup",
)
_MEDIUM_RISK_PATTERNS = (
    "rm -rf /", "mkfs", "dd if=/dev/", "> /dev/sd", "fdisk",
    "curl http://", "wget http://",  # 明文外传 (无 TLS 校验)
    "nc -e", "bash -i >& /dev/tcp", "/dev/tcp/",
    "ssh ", "scp ",   # 外连工具
)


def classify_escape_risk(script: str) -> str:
    """静态分级: high | medium | low (gate 用: high 直接拒, medium 进审批)。"""
    s = (script or "").lower()
    for pat in _HIGH_RISK_PATTERNS:
        if pat in s:
            return "high"
    for pat in _MEDIUM_RISK_PATTERNS:
        if pat in s:
            return "medium"
    return "low"


# ── 硬化 docker run 参数构造 ───────────────────────────────────────────────
HARDENING_DEFAULTS = {
    "network": "none",        # 默认禁网
    "read_only": True,        # 只读 rootfs
    "cap_drop_all": True,
    "no_new_privileges": True,
    "pids_limit": 256,
    "memory": "512m",
    "cpus": 1.0,
    "user": "65534:65534",    # nobody
    "seccomp": "default",     # 保持 docker 默认 seccomp profile
}


def build_hardened_docker_cmd(
    image: str,
    command: Iterable[str],
    *,
    workspace_dir: str = "/workspace",        # 宿主可写挂载点 (唯一可写区)
    host_workspace: str = "",
    env: Optional[Dict[str, str]] = None,     # 显式白名单 env (默认空 → 无宿主密钥)
    allow_network: bool = False,              # 白名单端口场景才 True
    extra_args: Optional[Iterable[str]] = None,
) -> List[str]:
    """产出硬化 docker run argv。

    Args:
        image: 镜像名
        command: 容器内命令 (list)
        workspace_dir: 容器内工作目录
        host_workspace: 宿主目录 (挂载为唯一可写区); 空则不挂载
        env: 显式注入 env (绝不透传宿主环境)
        allow_network: False(默认)=禁网; True=开网 (仅白名单场景)
    """
    cmd = ["docker", "run", "--rm"]
    if allow_network:
        cmd += ["--network", "bridge"]
    else:
        cmd += ["--network", "none"]
    cmd += ["--read-only"]
    cmd += ["--cap-drop", "ALL"]
    cmd += ["--security-opt", "no-new-privileges"]
    cmd += ["--pids-limit", str(HARDENING_DEFAULTS["pids_limit"])]
    cmd += ["--memory", HARDENING_DEFAULTS["memory"]]
    cmd += ["--cpus", str(HARDENING_DEFAULTS["cpus"])]
    cmd += ["--user", HARDENING_DEFAULTS["user"]]
    cmd += ["--workdir", workspace_dir]
    if host_workspace:
        cmd += ["-v", f"{host_workspace}:{workspace_dir}:rw"]   # 唯一可写挂载
    for k, v in (env or {}).items():
        cmd += ["-e", f"{k}={v}"]
    if extra_args:
        cmd += list(extra_args)
    cmd += [image]
    cmd += list(command)
    return cmd


def docker_run_cmd_str(image: str, command: Iterable[str], **kw) -> str:
    return " ".join(shlex.quote(a) for a in build_hardened_docker_cmd(image, command, **kw))
