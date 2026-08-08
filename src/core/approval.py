"""Approval Engine — 安全审批引擎

三级模式: manual(必须审批) / smart(智能判断) / off(跳过审批)
"""
# NOTE: 本文件为 meshctx 开源接口 stub。核心实现位于私有仓库 meshctx-core。
# 商业/完整版: pip install meshctx-core (需授权)。访问接口将抛 NotImplementedError。
from __future__ import annotations
from enum import Enum
from abc import ABC
from dataclasses import dataclass, field

class _MeshCtxStubProxy:
    """未导出符号的优雅降级代理: 导入成功, 调用/属性访问时提示需 meshctx-core。"""
    def __init__(self, name):
        self._name = name
    def __getattr__(self, attr):
        return _MeshCtxStubProxy(f"{self._name}.{attr}")
    def __call__(self, *args, **kwargs):
        raise NotImplementedError(f"meshctx-core required (private repo): {self._name}")
    def __repr__(self):
        return f"<meshctx stub {self._name}>"

def __getattr__(name):
    return _MeshCtxStubProxy(name)

class RiskLevel(str, Enum):
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    CRITICAL = 'critical'

class ApprovalMode(str, Enum):
    MANUAL = 'manual'
    SMART = 'smart'
    OFF = 'off'

@dataclass
class ApprovalResult:
    """审批检查结果"""
    requires_approval: bool = True
    reason: str = ''
    risk_level: RiskLevel = None
    yolo_override: bool = False
    action: str = 'prompt'
    def __post_init__(self):
        raise NotImplementedError("meshctx-core required (private repo)")


class ApprovalEngine:
    """安全审批引擎"""
    def __init__(self, mode: str = 'smart', yolo: bool = False):
        raise NotImplementedError("meshctx-core required (private repo)")

    def set_mode(self, mode: str):
        """切换审批模式：manual / smart / off"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def check(self, command: str, context: Optional[dict] = None) -> ApprovalResult:
        """检查命令是否需要审批"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def request_decision(self, command: str, reason: str = '') -> 'ApprovalDecision':
        """请求用户审批（同步/CLI 交互式三选一）。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def request(self, command: str, reason: str = '') -> bool:
        """请求用户审批（同步/CLI 模式）。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def stats(self) -> dict:
        """返回审批统计"""
        raise NotImplementedError("meshctx-core required (private repo)")



__all__ = ["RiskLevel", "ApprovalMode", "ApprovalResult", "ApprovalEngine", "set_mode", "check", "request_decision", "request", "stats"]
