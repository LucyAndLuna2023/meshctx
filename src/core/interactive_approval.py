"""InteractiveApproval — 终端三选一授权菜单 (OpenClaw-style)

当 meshctx 执行危险操作（文件系统/服务器/OS/浏览器）时，
操作人必须在终端确认：

    ⚠️ 需要授权: rm -rf /tmp/data
       风险等级: HIGH
    ────────────────────────────
      ▶ 同意执行
        拒绝执行
        给出操作建议 (需输入)
    ────────────────────────────
    ↑/↓ 选择 · Enter 确认 · 建议模式输入文本

返回 Decision:
    - approve          → 同意执行
    - deny             → 拒绝执行
    - suggest(text)    → 拒绝并给出操作建议（建议内容进入审计日志）
    - timeout          → 非交互/超时 → 默认拒绝（fail-safe）

纯 stdlib 实现（termios + ANSI），无第三方依赖。
非 TTY 环境自动降级为文本提示（y/n/s），无法交互时 fail-safe 拒绝。
"""
from __future__ import annotations

import os
import sys
import select
try:
    import termios  # Unix-only
    import tty      # Unix-only
except ImportError:
    termios = None
    tty = None
import logging
from dataclasses import dataclass, field
from typing import Optional, List

logger = logging.getLogger("meshctx.approval")

# ═══════════════════════════════════════════════════════════
# Decision model
# ═══════════════════════════════════════════════════════════

@dataclass
class ApprovalDecision:
    """操作人的授权决定。"""
    action: str            # "approve" | "deny" | "suggest" | "timeout"
    suggest_text: str = "" # suggest 模式下的操作建议
    auto: bool = False     # True = 非交互自动判定（非 TTY 且配置为 pass）

    @property
    def approved(self) -> bool:
        return self.action == "approve"

    @property
    def denied(self) -> bool:
        return self.action in ("deny", "timeout")

    def __repr__(self) -> str:
        if self.action == "suggest":
            return f"<ApprovalDecision suggest: {self.suggest_text[:40]}>"
        return f"<ApprovalDecision {self.action}>"


APPROVE = ApprovalDecision("approve")
DENY = ApprovalDecision("deny")
TIMEOUT = ApprovalDecision("timeout")


# ═══════════════════════════════════════════════════════════
# 终端按键读取（纯 stdlib）
# ═══════════════════════════════════════════════════════════

def _is_tty() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _read_key(timeout: float = 30.0) -> str:
    """读取单个按键。返回 'UP'/'DOWN'/'ENTER'/'ESC'/'x'/'CTRLC' 等。"""
    if termios is None or tty is None:
        # Windows fallback: msvcrt 无阻塞读取
        import msvcrt
        import time as _t
        deadline = _t.time() + timeout
        while _t.time() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch == "\x00" or ch == "\xe0":  # 方向键/功能键前缀
                    ch2 = msvcrt.getwch()
                    _map = {"H": "UP", "P": "DOWN", "M": "RIGHT", "K": "LEFT"}
                    return _map.get(ch2, ch2) if ch2 in _map else ch2
                if ch in ("\r", "\n"):
                    return "ENTER"
                if ch == "\x03":
                    return "CTRLC"
                if ch == "\x1b":
                    return "ESC"
                return ch
            _t.sleep(0.05)
        return "TIMEOUT"
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        # 等待首个按键
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        if not r:
            return "TIMEOUT"
        ch = sys.stdin.read(1)
        if ch == "\x1b":  # ESC 序列
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                seq = sys.stdin.read(2)
                if seq == "[A":
                    return "UP"
                if seq == "[B":
                    return "DOWN"
                if seq == "[C":
                    return "RIGHT"
                if seq == "[D":
                    return "LEFT"
            return "ESC"
        if ch == "\r" or ch == "\n":
            return "ENTER"
        if ch == "\x03":
            return "CTRLC"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ═══════════════════════════════════════════════════════════
# ANSI 渲染
# ═══════════════════════════════════════════════════════════

def _clear_lines(n: int) -> str:
    return "\x1b[1A\x1b[2K" * n


def _render_menu(action_desc: str, risk: str, selected: int,
                 options: List[str]) -> str:
    """渲染三选一菜单。selected 高亮项。"""
    lines = [
        "",
        f"  ⚠️  需要授权: {action_desc}",
        f"      风险等级: {risk}",
        "  ─────────────────────────────",
    ]
    for i, opt in enumerate(options):
        marker = "▶" if i == selected else " "
        lines.append(f"   {marker} {opt}")
    lines.append("  ─────────────────────────────")
    lines.append("  ↑/↓ 选择 · Enter 确认 · Ctrl+C 取消")
    return "\n".join(lines)


def _truncate(text: str, limit: int = 120) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


# ═══════════════════════════════════════════════════════════
# 交互授权主入口
# ═══════════════════════════════════════════════════════════

DEFAULT_OPTIONS = ["同意执行", "拒绝执行", "给出操作建议 (需输入)"]


def ask_approval(
    action_desc: str,
    risk: str = "MEDIUM",
    *,
    timeout: float = 30.0,
    auto_approve: Optional[bool] = None,
    suggest_max_chars: int = 500,
) -> ApprovalDecision:
    """请求操作人授权。

    Args:
        action_desc: 操作描述（如 "rm -rf /tmp/data"）。
        risk: 风险等级（LOW/MEDIUM/HIGH/CRITICAL）。
        timeout: 交互等待超时秒数；超时 → 拒绝（fail-safe）。
        auto_approve: 非 TTY 时的自动判定。
            True=通过, False=拒绝, None=按文本提示输入。
            默认 None；CRITICAL 默认拒绝。

    Returns:
        ApprovalDecision
    """
    desc = _truncate(action_desc)

    # CRITICAL 级别：即使配置 auto_approve 也需明确确认
    is_critical = risk.upper() == "CRITICAL"

    # ── 非 TTY 降级 ──
    if not _is_tty():
        if auto_approve is True and not is_critical:
            return ApprovalDecision("approve", auto=True)
        if auto_approve is False or is_critical:
            logger.warning(f"非交互环境且未授权 → 拒绝: {desc}")
            return TIMEOUT
        # 文本降级
        try:
            ans = input(
                f"\n⚠️ 需要授权 [{risk}]: {desc}\n"
                f"   [y]同意 [n]拒绝 [s]给出建议 (默认 n): "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return TIMEOUT
        if ans == "y":
            return APPROVE
        if ans.startswith("s"):
            try:
                text = input("   操作建议: ").strip()
            except (EOFError, KeyboardInterrupt):
                return TIMEOUT
            return ApprovalDecision("suggest", suggest_text=text[:suggest_max_chars])
        return DENY

    # ── 终端交互菜单 ──
    selected = 0
    options = list(DEFAULT_OPTIONS)
    menu = _render_menu(desc, risk, selected, options)
    sys.stdout.write(menu + "\n")
    sys.stdout.flush()

    try:
        while True:
            key = _read_key(timeout)
            if key == "UP":
                selected = (selected - 1) % len(options)
            elif key == "DOWN":
                selected = (selected + 1) % len(options)
            elif key == "ENTER":
                break
            elif key == "CTRLC" or key == "ESC":
                return DENY
            elif key == "TIMEOUT":
                logger.warning(f"授权超时 → 拒绝: {desc}")
                return TIMEOUT
            # 数字快捷键 1/2/3
            elif key in ("1", "2", "3"):
                selected = int(key) - 1
                break
            # 重绘菜单
            sys.stdout.write(_clear_lines(len(menu.splitlines())))
            sys.stdout.write(_render_menu(desc, risk, selected, options) + "\n")
            sys.stdout.flush()

        # 落定
        sys.stdout.write("\n")
        sys.stdout.flush()

        if selected == 0:
            return APPROVE
        if selected == 1:
            return DENY
        # 建议模式：退出 raw 模式后读文本
        try:
            text = input("   📝 操作建议: ").strip()
        except (EOFError, KeyboardInterrupt):
            return DENY
        if not text:
            return DENY
        return ApprovalDecision("suggest", suggest_text=text[:suggest_max_chars])

    finally:
        # 恢复终端
        try:
            sys.stdout.write("\x1b[0m")
            sys.stdout.flush()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# 便捷封装：与 terminal_sandbox 的 confirm_fn 签名对齐
# ═══════════════════════════════════════════════════════════

def make_confirm_fn(timeout: float = 30.0):
    """生成与 TerminalSession.execute(confirm_fn=...) 兼容的回调。

    签名: confirm_fn(code: str, assessment) -> bool
    返回 True = 授权执行。
    """
    def _confirm(code: str, assessment) -> bool:
        decision = ask_approval(
            action_desc=f"{assessment.tier.value}: {code}",
            risk=getattr(assessment, "reason", "MEDIUM"),
            timeout=timeout,
        )
        if decision.action == "suggest":
            logger.info(f"操作人建议: {decision.suggest_text}")
            # 建议即拒绝执行（操作人给了替代方案）
            return False
        return decision.approved
    return _confirm
