"""
MeshCtx Browser Safety Gate — 浏览器控制安全层 (v3.118)

在已有 BrowserTool (browser_tool.py, 256行 Playwright 封装) 外层包裹:
  ① 授权状态机 (idle → authorized → denied, 默认拒绝, 30min超时)
  ② 操作三级分级 (auto / confirm / blocked)
  ③ 危险 URL 黑名单 (payment/checkout/transfer/...)
  ④ confirm 队列 (并发安全, action_id 管理)
  ⑤ 审计日志 (内存, 可扩展接 observability)

设计原则 (002 审计通过 v2):
  - browser_tool.py 零改动, 只在外面包这一层
  - 所有浏览器操作必须经过 execute() 单点入口, 防止绕过
  - 会话内首次任何操作也走 confirm
"""
import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.browser_safety")

# ── 危险 URL 黑名单 (命中即 blocked, 一律拒绝) ──────────────
DANGEROUS_URL_PATTERNS = (
    "payment", "checkout", "transfer", "delete_account",
    "password/change", "wallet", "billing", "confirm_payment",
)

# 操作分级
LEVEL_AUTO = "auto"
LEVEL_CONFIRM = "confirm"
LEVEL_BLOCKED = "blocked"

# 需要 confirm 的操作类型 (写/交互类)
CONFIRM_ACTION_TYPES = {"click", "type", "press_key", "evaluate", "screenshot"}
# auto 操作类型 (只读类)
AUTO_ACTION_TYPES = {"navigate", "snapshot", "get_console"}

# 会话超时 (秒) — 30 分钟无操作自动断开
SESSION_TIMEOUT = 30 * 60


@dataclass
class PendingAction:
    """挂起的 confirm 级操作"""
    action_id: str
    action: Dict[str, Any]
    level: str
    reason: str
    created_at: float
    status: str = "pending"  # pending / approved / denied / expired


@dataclass
class AuditEntry:
    """审计记录"""
    ts: float
    action_id: str
    action_type: str
    url: str
    level: str
    decision: str  # executed / denied / pending / approved / error / authorize / revoke
    reason: str = ""


class BrowserSafetyGate:
    """浏览器控制安全闸门 — BrowserTool 外层单点"""

    def __init__(self, tool: Any = None, timeout: int = SESSION_TIMEOUT):
        self._tool = tool           # BrowserTool 实例 (懒加载)
        self._state = "idle"        # idle / authorized / denied
        self._authorized_at: Optional[float] = None
        self._last_activity: Optional[float] = None
        self._timeout = timeout
        self._first_action_done = False
        self._pending: Dict[str, PendingAction] = {}
        self._audit: List[AuditEntry] = []
        self._lock = asyncio.Lock()
        self._next_action_id = 0

    # ── 授权状态机 ─────────────────────────────────────────
    @property
    def state(self) -> str:
        """当前状态 (带超时自动回落)"""
        if (self._state == "authorized" and self._last_activity
                and (time.time() - self._last_activity) > self._timeout):
            self._state = "idle"
        return self._state

    async def authorize(self, cdp_url: str = "") -> Dict:
        """授权并启动浏览器 (默认拒绝 → 用户主动授权)
        cdp_url 非空 → 连接用户已开的 Chrome 复用登录态 (P1-2)"""
        if self._tool is None:
            from src.browser_tool import BrowserTool
            self._tool = BrowserTool()
        try:
            if cdp_url:
                r = await self._tool.connect_cdp(cdp_url)
                if "error" in r and not r.get("connected"):
                    return {"ok": False, "error": r["error"]}
            else:
                await self._tool._ensure_browser()
            # P1-1: 授权时加载已加密 cookie 恢复登录态
            try:
                from src.core.browser_cookie_vault import get_cookie_vault
                cookies = await get_cookie_vault().load()
                if cookies:
                    await self._tool.add_cookies(cookies)
                    logger.info(f"已从 vault 恢复 {len(cookies)} 个 cookie")
            except Exception as e:
                logger.warning(f"cookie 恢复失败: {e}")
        except Exception as e:
            return {"ok": False, "error": f"浏览器启动失败: {e}，请先 pip install playwright && playwright install chromium"}
        self._state = "authorized"
        self._authorized_at = time.time()
        self._last_activity = time.time()
        self._first_action_done = False
        self._audit_append("authorize", "", "auto", "executed", "用户授权")
        logger.info(f"Browser 已授权{' (CDP: ' + cdp_url + ')' if cdp_url else ''}")
        return {"ok": True, "state": "authorized", "cdp": cdp_url or ""}

    async def revoke(self) -> Dict:
        """撤销授权 + 保存cookie (P1-1) + 销毁浏览器进程"""
        if self._tool is not None:
            try:
                # P1-1: revoke 时加密保存当前 cookie 到 vault
                cookies = await self._tool.get_cookies()
                if cookies:
                    from src.core.browser_cookie_vault import get_cookie_vault
                    await get_cookie_vault().save(cookies)
                    logger.info(f"已加密保存 {len(cookies)} 个 cookie")
                await self._tool.close()
            except Exception:
                pass
        self._state = "denied"
        self._pending.clear()
        self._audit_append("revoke", "", "auto", "executed", "撤销授权")
        logger.info("Browser 已撤销")
        return {"ok": True, "state": "idle"}

    def session(self) -> Dict:
        """会话状态: 授权状态 + 待确认列表 + 最近审计"""
        st = self.state
        pending = []
        for pa in self._pending.values():
            if pa.status == "pending":
                pending.append({
                    "action_id": pa.action_id,
                    "action": pa.action,
                    "reason": pa.reason,
                    "created_at": pa.created_at,
                })
        return {
            "state": st,
            "authorized_at": self._authorized_at,
            "pending_confirm": pending,
            "recent_audit": self.audit_log(20),
        }

    # ── 操作分级 ───────────────────────────────────────────
    def _classify(self, action: Dict[str, Any]) -> tuple:
        """返回 (level, reason)"""
        atype = action.get("type", "")
        url = action.get("url", "") or ""

        # ① blocked: 危险 URL 黑名单
        if url and any(p in url.lower() for p in DANGEROUS_URL_PATTERNS):
            return LEVEL_BLOCKED, f"危险URL被拦截: {url}"

        # ② confirm: 写/交互类操作
        if atype in CONFIRM_ACTION_TYPES:
            return LEVEL_CONFIRM, f"{atype} 操作需用户确认"

        # ③ auto: 只读类操作, 但会话内首次操作也走 confirm
        if atype in AUTO_ACTION_TYPES:
            if not self._first_action_done:
                return LEVEL_CONFIRM, "会话内首次操作需用户确认"
            return LEVEL_AUTO, ""

        return LEVEL_CONFIRM, f"未知操作类型 {atype} 需确认"

    # ── 单点执行入口 ───────────────────────────────────────
    async def execute(self, action: Dict[str, Any]) -> Dict:
        """唯一入口: 所有浏览器操作必经此方法, 无法绕过"""
        if self.state != "authorized":
            return {"ok": False, "error": "未授权浏览器控制，请先调用 /api/browser/authorize", "code": 403}
        if self._tool is None:
            return {"ok": False, "error": "浏览器未初始化", "code": 500}

        level, reason = self._classify(action)
        action_id = self._new_action_id()

        if level == LEVEL_BLOCKED:
            self._audit_append(action.get("type", ""), action.get("url", ""),
                              level, "denied", reason, action_id)
            return {"ok": False, "error": f"危险操作已拦截: {reason}", "code": 403, "action_id": action_id}

        if level == LEVEL_CONFIRM:
            async with self._lock:
                self._pending[action_id] = PendingAction(
                    action_id, action, level, reason, time.time())
            self._audit_append(action.get("type", ""), action.get("url", ""),
                              level, "pending", reason, action_id)
            return {"ok": False, "need_confirm": True, "action_id": action_id,
                    "reason": reason, "code": 202}

        # auto: 直接执行
        return await self._run(action_id, action, level)

    async def confirm(self, action_id: str, approved: bool) -> Dict:
        """用户对挂起操作的确认/拒绝"""
        async with self._lock:
            pa = self._pending.pop(action_id, None)
        if pa is None:
            return {"ok": False, "error": "确认项不存在或已过期"}
        if not approved:
            self._audit_append(pa.action.get("type", ""), pa.action.get("url", ""),
                              pa.level, "denied", "用户拒绝", action_id)
            return {"ok": False, "error": "用户拒绝", "code": 403}
        self._audit_append(pa.action.get("type", ""), pa.action.get("url", ""),
                          pa.level, "approved", "", action_id)
        return await self._run(action_id, pa.action, pa.level)

    # ── 底层执行 (已过安全闸) ──────────────────────────────
    async def _run(self, action_id: str, action: Dict[str, Any], level: str) -> Dict:
        self._last_activity = time.time()
        self._first_action_done = True
        atype = action.get("type", "")
        try:
            tool = self._tool
            if atype == "navigate":
                result = await tool.navigate(action.get("url", ""))
            elif atype == "snapshot":
                result = await tool.snapshot(action.get("full", False))
            elif atype == "click":
                result = await tool.click(action.get("ref", ""))
            elif atype == "type":
                result = await tool.type_text(action.get("ref", ""), action.get("text", ""))
            elif atype == "press_key":
                result = await tool.press_key(action.get("key", ""))
            elif atype == "evaluate":
                result = await tool.evaluate(action.get("js", ""))
            elif atype == "screenshot":
                shot = await tool.screenshot()
                result = {"screenshot_b64": base64.b64encode(shot).decode() if shot else None}
            elif atype == "get_console":
                result = {"console": await tool.get_console()}
            else:
                result = {"error": f"未知操作: {atype}"}

            # 规范化返回值 (snapshot 返回 str, get_console 返回 list)
            if not isinstance(result, dict):
                result = {"result": result}

            has_err = "error" in result
            decision = "error" if has_err else "executed"
            self._audit_append(atype, action.get("url", ""), level, decision, "", action_id)
            result["ok"] = not has_err
            result["action_id"] = action_id
            return result
        except Exception as e:
            logger.error(f"browser action {atype} failed: {e}")
            self._audit_append(atype, action.get("url", ""), level, "error", str(e), action_id)
            return {"ok": False, "error": str(e), "action_id": action_id}

    # ── 工具方法 ───────────────────────────────────────────
    def _new_action_id(self) -> str:
        self._next_action_id += 1
        return f"a{int(time.time())}_{self._next_action_id}"

    # ── P1-4: 审计接 observability ────────────────────────
    def _audit_append(self, action_type: str, url: str, level: str,
                      decision: str, reason: str = "", action_id: str = "-") -> AuditEntry:
        """写内存审计 + 同步 observability trace span (瞬时事件, 立即闭合)"""
        entry = AuditEntry(time.time(), action_id, action_type, url, level, decision, reason)
        self._audit.append(entry)
        try:
            from src.core.observability import get_trace_logger
            tl = get_trace_logger()
            if tl is not None:
                # 审计为瞬时事件: start 后立即 end, 避免 span 悬挂泄漏
                span = tl.start_span("browser", f"browser.{action_type}",
                                     {"url": url, "level": level, "decision": decision, "reason": reason})
                tl.end_span(span, outputs={"decision": decision})
        except Exception:
            pass  # observability 不可用不影响核心
        return entry

    def audit_log(self, limit: int = 50) -> List[Dict]:
        """审计日志查询"""
        return [{
            "ts": a.ts, "type": a.action_type, "url": a.url,
            "level": a.level, "decision": a.decision, "reason": a.reason,
        } for a in self._audit[-limit:]]

    # 测试辅助
    def set_tool(self, tool: Any):
        """注入 mock 工具 (测试用)"""
        self._tool = tool


# ── 全局单例 (FastAPI 生命周期共享) ──────────────────────────
_gate: Optional[BrowserSafetyGate] = None
_gate_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    """延迟创建 lock, 避免模块导入时绑定事件循环"""
    global _gate_lock
    if _gate_lock is None:
        _gate_lock = asyncio.Lock()
    return _gate_lock


async def get_browser_gate() -> BrowserSafetyGate:
    """获取全局 BrowserSafetyGate 单例"""
    global _gate
    async with _get_lock():
        if _gate is None:
            _gate = BrowserSafetyGate()
        return _gate


def reset_browser_gate():
    """重置单例 (测试用)"""
    global _gate
    _gate = None
