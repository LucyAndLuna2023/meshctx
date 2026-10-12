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
