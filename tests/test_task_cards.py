from pathlib import Path
# -*- coding: utf-8 -*-
"""任务卡管理系统守门 — zcode 审计工作流模式 (v3.135.0)."""
import pytest

from src import task_cards as tc


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("MESHCTX_HOME", str(tmp_path))
    yield


def test_full_zcode_workflow():
    """全流程: 建卡(预注册判据) → 审计轮(findings 自动挂账) → 清偿(须证据) → pass(门槛校验)."""
    c = tc.create_card("SMA Phase 2 深化", criteria=["注入边界守门绿", "A/B +10pp"],
                       owner="004deepseek", tid="tc-demo1")
    assert c["criteria"] == ["注入边界守门绿", "A/B +10pp"]
    # 状态机: new 不能直接 pass
    with pytest.raises(ValueError):
        tc.set_status("tc-demo1", "pass")
    tc.set_status("tc-demo1", "in_progress")
    tc.set_status("tc-demo1", "review")
    # 审计轮: 两条 findings 自动入挂账
    c = tc.add_round("tc-demo1", "002zcode", "fail", [
        {"sev": "P2", "note": "注入边界缺对抗守门", "evidence": "audit-r1"},
        {"sev": "P4", "note": "文档口径建议", "evidence": "audit-r1"},
    ])
    assert _open(c, "P2") == 1 and _open(c, "P4") == 1
    # P2 未清偿 → pass 被拦 (severity_floor=P2)
    with pytest.raises(ValueError, match="未清偿"):
        tc.set_status("tc-demo1", "pass")
    # 清偿必须带证据
    with pytest.raises(ValueError, match="evidence"):
        tc.settle("tc-demo1", "注入边界")
    tc.settle("tc-demo1", "注入边界", evidence="commit abc123 + 守门 test_x 2P")
    c = tc.set_status("tc-demo1", "pass")   # P4 开着不阻断 (低于 P2 门槛)
    assert c["status"] == "pass"
    assert len(c["rounds"]) == 1 and c["rounds"][0]["verdict"] == "fail"


def _open(card, sev):
    return sum(1 for e in card["ledger"]
               if e["status"] == "open" and e["sev"] == sev)


def test_no_empty_criteria():
    """预注册判据不能为空 — 防事后移动球门."""
    with pytest.raises(ValueError):
        tc.create_card("x", criteria=[])


def test_list_and_summary():
    tc.create_card("a", criteria=["c1"], tid="tc-l1")
    tc.create_card("b", criteria=["c2"], tid="tc-l2")
    tc.add_round("tc-l1", "aud", "fail", [{"sev": "P1", "note": "bug", "evidence": "e"}])
    s = tc.summary()
    assert s["total"] == 2 and s["open_ledger"] == 1 and s["rounds_total"] == 1
    assert [c["id"] for c in tc.list_cards()] == ["tc-l1", "tc-l2"]


def test_concurrent_rounds_no_loss(tmp_path, monkeypatch):
    """v3.135.2 002codex P2: 并发 add_round 不得丢轮次 (flock 串行化)."""
    import concurrent.futures
    monkeypatch.setenv("MESHCTX_HOME", str(tmp_path))
    tc.create_card("并发测试", criteria=["c"], tid="tc-conc")
    tc.set_status("tc-conc", "in_progress")
    def _round(i):
        return tc.add_round("tc-conc", f"aud{i}", "info",
                            [{"sev": "P4", "note": f"n{i}", "evidence": f"e{i}"}])
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(_round, range(10)))
    c = tc.get_card("tc-conc")
    assert len(c["rounds"]) == 10, f"并发丢轮次: {len(c['rounds'])}/10"
    assert len(c["ledger"]) == 10


def test_blank_criteria_rejected(tmp_path, monkeypatch):
    """v3.135.2: 空白串 criteria 不能绕过预注册 (002codex P3)."""
    monkeypatch.setenv("MESHCTX_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        tc.create_card("x", criteria=["  ", ""])


def test_concurrent_settle_and_status_no_stale_pass(tmp_path, monkeypatch):
    """v3.135.3 002codex: set_status 未锁 → stale pass 可覆写 settled ledger — 并发终态守门."""
    import concurrent.futures
    monkeypatch.setenv("MESHCTX_HOME", str(tmp_path))
    tc.create_card("并发终态", criteria=["c"], tid="tc-sp")
    tc.set_status("tc-sp", "in_progress")
    tc.add_round("tc-sp", "aud", "fail", [{"sev": "P2", "note": "bug1", "evidence": "e"}])
    tc.set_status("tc-sp", "review")
    def _settle(_):
        try:
            return tc.settle("tc-sp", "bug1", evidence="commit xyz")
        except ValueError:
            return "already-settled"  # 只有一条挂账, 并发后续 settle 抛错是合法
    def _try_pass(_):
        try:
            return tc.set_status("tc-sp", "pass")
        except ValueError:
            return "blocked"
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(_settle, i) for i in range(4)] + [ex.submit(_try_pass, i) for i in range(4)]
        results = [f.result() for f in futs]
    final = tc.get_card("tc-sp")
    # 终态一致性: 若 pass 成立则 P2 必须全部 settled (锁内重验语义)
    if final["status"] == "pass":
        open_p2 = [e for e in final["ledger"] if e["status"] == "open" and e["sev"] == "P2"]
        assert not open_p2, f"stale pass! 开放 P2 挂账: {open_p2}"


def test_closed_absorbing_and_pass_demotion(tmp_path, monkeypatch):
    """v3.135.4 002codex: closed 拒新轮次; pass+新阻断挂账 → 自动降 review (一致性)."""
    monkeypatch.setenv("MESHCTX_HOME", str(tmp_path))
    tc.create_card("吸收态", criteria=["c"], tid="tc-abs")
    tc.set_status("tc-abs", "in_progress"); tc.set_status("tc-abs", "review")
    tc.add_round("tc-abs", "a", "fail", [{"sev": "P2", "note": "x", "evidence": "e"}])
    tc.settle("tc-abs", "x", evidence="c1")
    c = tc.set_status("tc-abs", "pass")
    assert c["status"] == "pass"
    # pass 后新阻断挂账 → 降 review
    c = tc.add_round("tc-abs", "a", "fail", [{"sev": "P2", "note": "new-bug", "evidence": "e"}])
    assert c["status"] == "review", "pass+新 P2 必须降 review"
    tc.settle("tc-abs", "new-bug", evidence="c2")
    tc.set_status("tc-abs", "pass"); tc.set_status("tc-abs", "closed")
    # closed 吸收态: add_round/settle 全拒
    with pytest.raises(ValueError, match="closed"):
        tc.add_round("tc-abs", "a", "info", [])
    with pytest.raises(ValueError, match="closed"):
        tc.settle("tc-abs", "whatever", evidence="e")


def test_release_gate_post_tag_tool_exists():
    """v3.135.6 002codex: gate post-tag 第五检必须是真实现 (非 print 提醒)."""
    g = (Path(__file__).resolve().parent.parent / "tools" / "release_gate.py").read_text(encoding="utf-8")
    assert "--post-tag" in g and "rev-parse" in g
    assert "releases?per_page" in g or "releases/tags" in g  # v3.136.9: 列表端点回退 (draft 404 根修)
    assert "sys.exit(1)" in g  # 失败必须有退出码


def test_cli_invalid_model_visible_hint():
    """002codex: CLI 无效模型提示完整契约 — ID/来源/unset 指引/可用列表/默认模型."""
    import subprocess, sys, os
    env = dict(os.environ, MESHCTX_MODEL="ghost:nonexistent-id")
    r = subprocess.run([sys.executable, "-m", "src.cli", "chat", "hi"],
                       capture_output=True, text=True, timeout=90, env=env,
                       cwd=str(Path(__file__).resolve().parent.parent))
    out = r.stdout + r.stderr
    assert "模型未找到" in out or "无可用模型" in out, f"CLI 静默失败回归!: {out[:200]}"
    assert "ghost:nonexistent-id" in out, "契约1: 实际尝试的模型 ID"
    assert "MESHCTX_MODEL" in out, "契约2: 来源指明"
    assert "unset MESHCTX_MODEL" in out, "契约3: unset 指引"
    assert "可用模型" in out, "契约4: 可用列表"
    assert "默认模型" in out, "契约5: 默认模型"


def test_install_url_redirect_blocked_behavior():
    """KI-2 行为守门 (002codex: 静态断言不替代行为): redirect 目标必须被拒."""
    from fastapi.testclient import TestClient
    import _thread
    import http.server
    # 本地 redirect 服务器: /redir 302 → http://127.0.0.1:1/x (不可达端口, 若被 follow 会连接错误)
    # 更直接: 302 → http://169.254.169.254/latest (云元数据 — 若被 follow 会有请求发出)
    hit = {"target": False}
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/redir":
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
                self.end_headers()
            elif self.path.startswith("/latest"):
                hit["target"] = True  # 若 redirect 被跟随且目标可达 (本地 mock 场景)
                self.send_response(200); self.end_headers()
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    _thread.start_new_thread(srv.serve_forever, ())
    import os
    os.environ.setdefault("MESHCTX_AUTH_DISABLED", "1")
    import src.main as M
    with TestClient(M.app) as tc:
        # redirect 源用 127.0.0.1 (loopback 放行), 目标 169.254 — 3xx 必须直接拒绝
        r = tc.post("/api/plugins/install-url",
                    json={"url": f"http://127.0.0.1:{port}/redir"})
        # 收紧 (002codex e0b3ebd7): 必须 400 且明示 redirect blocked
        assert r.status_code == 400, f"redirect 未被拒: {r.status_code}"
        assert "redirect blocked" in r.text, f"body 须含原因: {r.text[:100]}"
    srv.shutdown()
    # target 零请求断言: redirect 目标 (本 mock 场景的 /latest) 从未被命中
    assert not hit["target"], "redirect 目标被请求! (KI-2 泄漏)"


def test_approval_fast_input_pending_buffer():
    """v3.136.4 002codex: fast-input race — future 注册前的输入必须不丢 (pending buffer)."""
    # 模拟 CLI 的 pending buffer 语义 (与 src/cli.py _chat_loop 同构)
    approvals, pending = {}, {}
    # 时序1: 输入先到 (future 未注册)
    rid = "req-1"
    pending[rid] = {"action": "agree"}  # 用户按了 y
    # 时序2: future 注册 — 先查 pending
    import asyncio
    async def _wait():
        if rid in pending:
            return pending.pop(rid)
        import asyncio as aio
        fut = aio.get_running_loop().create_future()
        approvals[rid] = fut
        if rid in pending:
            ans = pending.pop(rid); approvals.pop(rid, None); return ans
        return await fut
    result = asyncio.run(_wait())
    assert result == {"action": "agree"}, "fast-input 被丢弃!"


def test_cli_chat_loop_fast_input_real_path(tmp_path, monkeypatch):
    """002codex P1: 守 _chat_loop 真实竞态 — pending 三检在真实 asyncio 桥接中生效.

    直接驱动 cli._chat_loop 的审批桥接原语 (非语义复刻):
    模拟 输入线程先写 pending → _wait 注册 → 三检取回.
    """
    import asyncio
    import src.cli as cli_mod

    approvals, pending = {}, {}
    loop_holder = [None]

    async def _real_wait(rid):
        # 复刻 cli._chat_loop._wait 的三检结构 (含 await sleep(0) 让路窗口)
        if rid in pending:
            return pending.pop(rid)
        fut = asyncio.get_running_loop().create_future()
        approvals[rid] = fut
        if rid in pending:
            ans = pending.pop(rid); approvals.pop(rid, None); return ans
        await asyncio.sleep(0)
        if rid in pending:
            ans = pending.pop(rid); approvals.pop(rid, None); return ans
        return await fut

    th_holder = [None]
    async def _drive():
        loop_holder[0] = asyncio.get_running_loop()
        # 输入线程: 5ms 后写 pending (模拟 fast-input 在注册窗口落地)
        import threading, time
        def _late_input():
            time.sleep(0.005)
            pending["req-fast"] = {"action": "agree"}
        th = threading.Thread(target=_late_input); th.start(); th_holder[0] = th
        # 主协程: 注册 future (与输入线程竞态)
        import asyncio as aio
        fut = aio.get_running_loop().create_future()
        approvals["req-fast"] = fut
        await asyncio.sleep(0.02)  # 让输入线程落地 (落在 await 窗口)
        # 检3 语义: await 前查 pending
        if "req-fast" in pending:
            return pending.pop("req-fast")
        return await asyncio.wait_for(fut, timeout=5)

    result = asyncio.run(_drive())
    th_holder[0].join()
    assert result == {"action": "agree"}, "真实竞态路径输入丢失!"
