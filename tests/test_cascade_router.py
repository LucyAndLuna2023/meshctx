from pathlib import Path
# -*- coding: utf-8 -*-
"""SMA Phase 1 级联路由守门 — 三级分级/工具下限/升级触发."""
from src.cascade_router import classify_task, route, should_escalate


def test_l0_greeting_and_translation():
    assert classify_task("你好！") == "L0"
    assert classify_task("thanks") == "L0"
    assert classify_task("翻译这段话") == "L0"
    assert classify_task("总结一下") == "L0"


def test_l2_architecture_and_long_analysis():
    assert classify_task("请给出系统架构设计方案") == "L2"
    assert classify_task("分析这段代码的根因") == "L2"
    assert classify_task("x" * 900) == "L2"  # 长文分析


def test_l1_default_and_tool_floor():
    assert classify_task("写一个函数实现快排") == "L1"
    assert classify_task("你好", has_tools=True) == "L1"  # 工具任务不低于 L1


def test_route_explicit_models_override():
    out = route("你好", models={"L0": "ollama:qwen3:0.6b"})
    assert out["tier"] == "L0" and out["model"] == "ollama:qwen3:0.6b"


def test_escalate_trigger():
    assert should_escalate(fail_count=2) is True
    assert should_escalate(fail_count=1, validation_failed=True) is True
    assert should_escalate(fail_count=0) is False


# ── Phase 1 深化: registry 接线 + 降级链 + 计量 ─────────────

class FakeRegistry:
    def __init__(self, entries, default=""):
        self._entries = entries
        self._default = default


def test_resolve_models_full():
    reg = FakeRegistry({
        "ollama:qwen3": {"provider": "ollama"},
        "deepseek:flash": {"provider": "deepseek"},
        "anthropic:opus": {"provider": "anthropic"},
    }, default="deepseek:flash")
    m = __import__("src.cascade_router", fromlist=["resolve_models"]).resolve_models(reg)
    assert m["L0"] == "ollama:qwen3"
    assert m["L1"] == "deepseek:flash"
    assert m["L2"] == "anthropic:opus"


def test_resolve_models_degrade_no_ollama():
    """L0 缺 → 降级 L1 (本地模型未装时级联不中断)."""
    reg = FakeRegistry({"deepseek:flash": {"provider": "deepseek"}}, default="deepseek:flash")
    m = __import__("src.cascade_router", fromlist=["resolve_models"]).resolve_models(reg)
    assert m["L0"] == "deepseek:flash" and m["L1"] == "deepseek:flash"


def test_usage_meter_and_saving():
    from src.cascade_router import record_usage, usage_report, usage_reset
    usage_reset()  # 全局单例隔离 (测试顺序依赖根修)
    record_usage("L0", 100)
    record_usage("L0", 50)
    record_usage("L2", 200)
    r = usage_report()
    assert r["by_tier"]["L0"]["calls"] == 2 and r["by_tier"]["L0"]["tokens"] == 150
    assert r["saved_tokens_estimate"] == 150 * 50  # L0_SAVING_FACTOR 默认 50


# ── Phase 1 收尾: chat 端点接线守门 ─────────────────────────

def test_pick_user_model_always_wins():
    """用户显式指定模型 → 级联不介入 (铁律: 用户优先)."""
    from src.cascade_router import pick_model_for_message
    out = pick_model_for_message("你好", requested_model="anthropic:opus")
    assert out["tier"] == "user" and out["model"] == "anthropic:opus"


def test_pick_cascade_off_falls_back(monkeypatch):
    from src.cascade_router import pick_model_for_message
    monkeypatch.setenv("MESHCTX_CASCADE", "0")
    monkeypatch.setenv("MESHCTX_L1_MODEL", "deepseek:flash")
    out = pick_model_for_message("分析这段代码的根因", cascade_on=False)
    assert out["model"] == "" and out["tier"] == "default"  # 返回空 → 调用方回落 registry 默认 (旧行为等价)


def test_pick_needs_tools_never_below_l1():
    from src.cascade_router import pick_model_for_message
    out = pick_model_for_message("帮我查看文件并执行脚本", registry=FakeRegistry(
        {"ollama:qwen3": {"provider": "ollama"},
         "deepseek:flash": {"provider": "deepseek"}}, default="deepseek:flash"))
    assert out["tier"] in ("L1", "L2"), "工具意图消息不得落 L0"


def test_pick_simple_greeting_uses_l0_when_available():
    from src.cascade_router import pick_model_for_message
    out = pick_model_for_message("你好", registry=FakeRegistry(
        {"ollama:qwen3": {"provider": "ollama"},
         "deepseek:flash": {"provider": "deepseek"}}, default="deepseek:flash"))
    assert out["tier"] == "L0" and out["model"] == "ollama:qwen3"


def test_usage_reset():
    from src.cascade_router import record_usage, usage_report, usage_reset
    record_usage("L1", 10)
    usage_reset()
    assert usage_report()["total_tokens"] == 0


def test_sma_endpoint_registered():
    """SMA 轻端点已注册 (契约: 存在且带校验)."""
    import src.main as M
    routes = [getattr(r, "path", "") for r in M.app.routes]
    assert "/api/chat/sma" in routes
    assert "/api/usage/report" in routes
    assert "/api/usage/reset" in routes


# ── 语言策略: 推理模型 user 尾部指令 ─────────────────────────

def test_language_notice_appended_to_last_user():
    from src.chat_tools import append_language_notice
    msgs = [{"role": "system", "content": "sys"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "再来一个"}]
    append_language_notice(msgs)
    assert "Respond in English" in msgs[3]["content"]   # 最后一条 user
    assert "Respond in English" not in msgs[1]["content"]  # 历史 user 不动


def test_language_notice_idempotent():
    from src.chat_tools import append_language_notice
    msgs = [{"role": "user", "content": "hi"}]
    append_language_notice(msgs)
    once = msgs[0]["content"]
    append_language_notice(msgs)
    assert msgs[0]["content"] == once  # 不重复追加


def test_confirm_panel_overflow_guard():
    """用户实测: 授权UI溢出屏幕 — v3.133.7 终修: position:fixed bottom bar.

    前三版 (100vw/100dvw/width:100%) 全失败 — 根因: confirmPanel 不在
    .chat-main/.messages DOM 内 (chat-main 闭合位置 < confirmPanel 位置),
    width:100% 相对错误父级计算。唯一可靠: fixed 定位三边锚定。
    """
    h = Path(__file__).resolve().parent.parent / "templates" / "chat.html"
    t = h.read_text(encoding="utf-8")
    # 面板必须 fixed 定位 + 三边锚定
    assert "position: fixed" in t, "面板必须 fixed (前三版相对父级 width 全失败)"
    assert "bottom: 0; left: 0; right: 0" in t, "三边锚定"
    assert "max-width: 100vw" in t, "视口宽上限"
    assert "overflow-wrap: anywhere" in t, "11 语言长词断行"
    assert "max-height: 60vh" in t, "高度上限"
    # 选项/标题/自定义输入同样受控
    assert "confirm-options" in t and "confirm-custom" in t
    assert ".confirm-panel * { max-width: 100%" in t
    assert "flex-wrap: wrap" in t and "flex-shrink: 0" in t
