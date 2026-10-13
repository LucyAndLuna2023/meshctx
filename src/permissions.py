# -*- coding: utf-8 -*-
"""meshctx 权限档位管理 (v3.136.0) — 对标 zcode/codex/deepseek harness 的权限下拉.

三档模式 (config.yaml permissions.mode):
  full        完全权限 — 所有工具直接执行, 不弹审批 (信任环境/沙箱)
  standard    标准 (默认) — 危险操作审批 (写覆盖/远程/危险命令 — 原行为)
  restricted  全部审批 — 每次工具调用都需用户批准

细粒度 (与 mode 叠加):
  deny_tools:  [tool, ...]  黑名单 — 直接拒绝执行 (不需审批, 直接 deny)
  allow_tools: [tool, ...]  白名单 — 这些工具即使 restricted 也直接放行

优先级: deny_tools > allow_tools > mode 规则
CLI 与 UI 共用同一判定入口 needs_approval_unified().
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_MODES = ("full", "standard", "restricted")


def _config_path() -> Path:
    profile = os.environ.get("MESHCTX_PROFILE")
    if not profile:
        af = Path.home() / ".meshctx" / ".active_profile"
        if af.exists():
            profile = af.read_text().strip()
    base = Path.home() / ".meshctx" if (not profile or profile == "default") \
        else Path.home() / ".meshctx" / "profiles" / profile
    return base / "config.yaml"


def load_permissions() -> Dict[str, Any]:
    """读 config.yaml permissions 段 (缺省 = standard + 空黑白名单)."""
    import yaml
    p = _config_path()
    try:
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        cfg = {}
    perm = (cfg.get("permissions") or {}) if isinstance(cfg.get("permissions"), dict) else {}
    mode = perm.get("mode", "standard")
    if mode not in _MODES:
        mode = "standard"
    return {
        "mode": mode,
        "deny_tools": list(perm.get("deny_tools") or []),
        "allow_tools": list(perm.get("allow_tools") or []),
    }


def save_permissions(mode: str, deny_tools: List[str] = None,
                     allow_tools: List[str] = None) -> Dict[str, Any]:
    """写 config.yaml permissions 段 (保留其余配置)."""
    import yaml
    if mode not in _MODES:
        raise ValueError(f"非法权限档位: {mode} (合法: {list(_MODES)})")
    p = _config_path()
    cfg = {}
    if p.exists():
        try:
            cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            cfg = {}
    cfg.setdefault("permissions", {})
    cfg["permissions"]["mode"] = mode
    # v3.136.0b: None = 保留现有值 (模式切换不得清空黑白名单 — 守门 test_deny_survives)
    if deny_tools is not None:
        cfg["permissions"]["deny_tools"] = [t.strip() for t in deny_tools if t.strip()]
    if allow_tools is not None:
        cfg["permissions"]["allow_tools"] = [t.strip() for t in allow_tools if t.strip()]
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False),
                   encoding="utf-8")
    os.replace(tmp, p)
    return load_permissions()


def evaluate(tool_name: str, args: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """统一判定入口 — 返回 (decision, reason).

    decision: "allow" | "deny" | "approval"
    兼容并扩展现有 _needs_approval 语义:
      - full: allow (除非命中 deny_tools)
      - standard: 原有危险判定 (写覆盖/远程/危险命令) → approval
      - restricted: 全部 approval (除非命中 allow_tools)
    """
    perm = load_permissions()
    deny, allow = perm["deny_tools"], perm["allow_tools"]
    if tool_name in deny:
        return "deny", f"工具在 deny_tools 黑名单中 ({tool_name})"
    if tool_name in allow:
        return "allow", None
    mode = perm["mode"]
    if mode == "full":
        return "allow", None
    if mode == "restricted":
        return "approval", f"restricted 模式: 所有工具调用需批准 ({tool_name})"
    # standard: 危险判定 (原 _needs_approval 逻辑, 从 main.py 收编)
    return _standard_risk(tool_name, args)


def _standard_risk(tool_name: str, args: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """standard 档危险判定 (与 main.py::_needs_approval 同规则 — 收编为唯一实现)."""
    if tool_name == "write_file" and args.get("if_exists") == "overwrite":
        return "approval", "修改已有文件内容 (write_file overwrite)"
    if tool_name in ("remote_write", "remote_exec"):
        return "approval", f"远程操作 ({tool_name}) 需用户授权"
    if tool_name == "terminal":
        import re as _re
        cmd = args.get("cmd", "") or ""
        if _re.search(r"\b(rm|rmdir|unlink|del|remove|mv|cp)\b", cmd):
            return "approval", "删除/移动/复制文件命令 (terminal)"
        try:
            from src.core.approval import check as _approval_check
            r = _approval_check(cmd, {})
            if r.requires_approval:
                return "approval", f"危险命令 ({r.reason})"
        except Exception:
            pass
    return "allow", None
