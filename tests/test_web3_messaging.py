"""Test Web3 去中心化消息记录层 (HashChainLedger + LocalJournal)。

覆盖:
1. append 链式累积 (prev_hash 正确)
2. verify: 正常链 OK
3. verify: 篡改 payload 检测
4. verify: 丢消息 (链断裂) 检测
5. LocalJournal 持久化 + 重启恢复
6. Web3MessagingLayer send/recv + verify + head_hash
7. 模拟 Redis 挂: journal 本地文件仍完整可恢复
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.web3_messaging import HashChainLedger, LocalJournal, Web3MessagingLayer


def test_append_chain():
    led = HashChainLedger()
    e0 = led.append("A", "m0", {"t": "hi"}, kind="dm")
    e1 = led.append("B", "m1", {"t": "yo"}, kind="dm")
    assert e0["prev_hash"] == "0" * 64
    assert e1["prev_hash"] == e0["entry_hash"]
    assert e0["seq"] == 0 and e1["seq"] == 1
    ok, bad = led.verify()
    assert ok and bad is None
    assert len(led.head_hash()) == 64


def test_verify_detects_tamper():
    led = HashChainLedger()
    led.append("A", "m0", {"t": "hi"})
    led.append("B", "m1", {"t": "yo"})
    # 篡改第一条 payload
    led._entries[0]["payload"]["t"] = "EVIL"
    ok, bad = led.verify()
    assert not ok
    assert bad == 0


def test_verify_detects_missing():
    led = HashChainLedger()
    led.append("A", "m0", {"t": "hi"})
    led.append("B", "m1", {"t": "yo"})
    led.append("C", "m2", {"t": "ok"})
    # 模拟丢消息: 删除中间一条 → 链断裂
    led._entries.pop(1)
    ok, bad = led.verify()
    assert not ok
    assert bad == 1  # 第二条 prev_hash 与第一条断裂


def test_journal_persistence_and_recovery():
    tmp = tempfile.mkdtemp()
    try:
        name = "test_node"
        j1 = LocalJournal(name, Path(tmp))
        e = {"seq": 0, "sender": "A", "msg_id": "m0", "payload": {"t": "hi"},
             "entry_hash": "h" * 64}
        j1.append(e)
        j1.close()

        j2 = LocalJournal(name, Path(tmp))  # 重启 (新实例)
        loaded = j2.load()
        assert len(loaded) == 1
        assert loaded[0]["msg_id"] == "m0"
        j2.close()
    finally:
        shutil.rmtree(tmp)


def test_layer_send_recv_verify():
    tmp = tempfile.mkdtemp()
    try:
        layer = Web3MessagingLayer("node_a", Path(tmp))
        layer.log_send("004/meshctx", "msg1", {"text": "hi"}, kind="dm")
        layer.log_receive("002/meshctx", "msg2", {"text": "hello"}, kind="dm")
        ok, bad = layer.verify()
        assert ok and bad is None
        assert len(layer.load_journal()) == 2
        assert len(layer.head_hash()) == 64
    finally:
        shutil.rmtree(tmp)


def test_redis_down_recovery():
    """模拟 Redis 挂: journal 本地文件仍完整, 可重建链并验证。"""
    tmp = tempfile.mkdtemp()
    try:
        layer = Web3MessagingLayer("node_b", Path(tmp))
        layer.log_send("004/meshctx", "r1", {"task": "write"})
        layer.log_send("004/meshctx", "r2", {"task": "review"})
        layer.log_receive("002/meshctx", "r3", {"ok": True})
        head_before = layer.head_hash()

        # 模拟 Redis 挂 + 进程重启: 用 journal 重建全新 layer
        layer2 = Web3MessagingLayer("node_b", Path(tmp))
        assert len(layer2.load_journal()) == 3
        ok, bad = layer2.verify()
        assert ok and bad is None
        assert layer2.head_hash() == head_before  # 链头一致 → 消息未丢未改
    finally:
        shutil.rmtree(tmp)
