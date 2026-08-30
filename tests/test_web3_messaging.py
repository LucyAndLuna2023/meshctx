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


def test_recovery_detects_missing_middle():
    """P1 (002meshctx 审计): 恢复时丢中间消息必须能被 verify 检出。

    修复前: __init__ 用 append 重建链 (重编号 seq/重算 prev_hash),
    删中间行后重建链自我一致 → verify=True (检测不出)。
    修复后: restore 载入原始 entry, 中间断裂 → prev_hash 不匹配 → verify=False。
    """
    import tempfile, shutil
    from pathlib import Path
    from src.core.web3_messaging import Web3MessagingLayer

    tmp = tempfile.mkdtemp()
    try:
        layer = Web3MessagingLayer("p1_test", Path(tmp))
        layer.log_send("A", "m0", {"t": "hi"})
        layer.log_send("B", "m1", {"t": "yo"})
        layer.log_send("C", "m2", {"t": "ok"})
        assert layer.verify() == (True, None)

        # 模拟: 手动删除中间一条 (如磁盘损坏/误操作)
        lines = layer.journal.path.read_text(encoding="utf-8").splitlines()
        # 找到 seq=1 的行删除
        import json as _j
        kept = [ln for ln in lines if not (ln.strip() and _j.loads(ln).get("seq") == 1)]
        layer.journal.path.write_text("\n".join(kept) + "\n", encoding="utf-8")

        # 重启恢复 (新实例从 journal 载入)
        layer2 = Web3MessagingLayer("p1_test", Path(tmp))
        ok, bad = layer2.verify()
        assert not ok, "删除中间消息后 verify 必须失败 (P1 回归)"
        assert bad == 1, f"损坏应在 seq=1, got {bad}"
    finally:
        shutil.rmtree(tmp)


def test_journal_permissions_0600():
    """P3 (002meshctx 审计): journal 文件权限必须 0600 (含敏感 payload)。"""
    import tempfile, shutil, os, stat
    from pathlib import Path
    from src.core.web3_messaging import Web3MessagingLayer

    tmp = tempfile.mkdtemp()
    try:
        layer = Web3MessagingLayer("perm_test", Path(tmp))
        layer.log_send("A", "m0", {"secret": "s3cret"})
        mode = stat.S_IMODE(os.stat(layer.journal.path).st_mode)
        assert mode == 0o600, f"journal 权限应为 0600, got {oct(mode)}"
    finally:
        shutil.rmtree(tmp)


def test_tail_truncation_detected_via_head_file():
    """P3-1 (002codex 审计): 尾部截断无法被 verify 检出, 但 head 文件对比可检出。"""
    import tempfile, shutil, json as _j
    from pathlib import Path
    from src.core.web3_messaging import Web3MessagingLayer

    tmp = tempfile.mkdtemp()
    try:
        layer = Web3MessagingLayer("tail_test", Path(tmp))
        layer.log_send("A", "m0", {"t": "hi"})
        layer.log_send("B", "m1", {"t": "yo"})
        head_after = layer.persist_head()

        # 模拟尾部截断: 删除最后一行
        lines = layer.journal.path.read_text(encoding="utf-8").splitlines()
        layer.journal.path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

        # 重启恢复
        layer2 = Web3MessagingLayer("tail_test", Path(tmp))
        ok, bad = layer2.verify()
        assert ok, "尾部截断本身 verify 通过 (append-only 固有限制)"
        assert layer2.stats()["head_file_mismatch"] is True, \
            "head 文件对比应检出尾部截断 (P3-1 回归)"
    finally:
        shutil.rmtree(tmp)
