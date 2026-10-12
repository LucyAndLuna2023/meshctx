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
