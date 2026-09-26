# -*- coding: utf-8 -*-
"""hub_receipt_watch 守门 — INCIDENTS I-3 根治件 (送审超时无回执告警)."""
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "tools"))
import hub_receipt_watch as w


@pytest.fixture()
def jdir(tmp_path, monkeypatch):
    jd = tmp_path / "web3_journal"
    jd.mkdir()
    monkeypatch.setattr(w, "JOURNAL_DIR", jd)
    return jd


def _write(jd, entries):
    (jd / "deepseek_meshctx.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries), encoding="utf-8")


def _send(mid, msg, ts):
    return {"sender": "deepseek>send", "msg_id": mid, "ts": ts, "kind": "send",
            "payload": {"to_profile": "002:meshctx", "message": msg}}


NOW = "2026-09-26T12:00:00+00:00"
OLD = "2026-09-26T02:00:00+00:00"  # 10h 前


def test_overdue_unacked_alerted(jdir):
    """送审超时无回执 → ALERT (I-3 场景: 4 天才发现的事故本工具 6h 就报)."""
    _write(jdir, [_send("AUD1", "[送审] v3.131.17 请审计", OLD)])
    out = w.watch(hours=6)
    assert out["verdict"] == "ALERT"
    assert out["unacked_overdue"][0]["msg_id"] == "AUD1"
    assert out["unacked_overdue"][0]["age_hours"] >= 6


def test_acked_within_threshold_ok(jdir):
    """回执引用原 msg_id → 不告警."""
    _write(jdir, [
        _send("AUD2", "[送审] v3.131.17 请审计", OLD),
        {"sender": "deepseek>recv", "msg_id": "r1", "ts": NOW, "kind": "recv",
         "payload": {"message": "收到 AUD2, PASS"}},
    ])
    assert w.watch(hours=6)["verdict"] == "OK"


def test_non_expect_reply_ignored(jdir):
    """普通消息 (无送审标记) 不纳入回执跟踪."""
    _write(jdir, [_send("CHAT1", "随便聊聊", OLD)])
    out = w.watch(hours=6)
    assert out["checked"] == 0 and out["verdict"] == "OK"


def test_recent_send_below_threshold_not_alerted(jdir):
    _write(jdir, [_send("AUD3", "[送审] 刚发出 1h", NOW)])
    assert w.watch(hours=6)["verdict"] == "OK"
