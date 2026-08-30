#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web3 去中心化消息记录层 — 哈希链账本 + 本地日志 (v1)

解决集群通讯 Redis 单点问题 (用户反馈 2026-08-30):
1. Redis 挂 → 消息乱/丢失/无记录 → 本模块提供 append-only 本地日志 + fsync,
   Redis 挂不丢, 任意节点可从 journal 重建
2. 无完整性校验 → 本模块提供哈希链: 每条消息 {seq, prev_hash, payload_hash},
   链式累积, 篡改/丢消息可检测 (verify)
3. 无跨节点共识 → 链头哈希 (head_hash) 可每日锚定 (IPFS CID / 广播),
   任一节点可验证"消息未被改"

设计:
- HashChainLedger: 哈希链账本 (纯逻辑, 无 IO, 可单测)
- LocalJournal: append-only JSONL 本地日志 (fsync 持久化)
- Web3MessagingLayer: 组合两者 + 收发钩子 (与 hermes_connector 集成)

零外部依赖: 仅标准库 (hashlib/json/pathlib/threading)。
IPFS 锚定是 Phase 2 (有网关时可选), 本 Phase 不依赖网络。
"""
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 默认日志目录 (与 meshctx 数据目录一致)
DEFAULT_JOURNAL_DIR = Path.home() / ".meshctx" / "web3_journal"


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8", errors="replace")).hexdigest()


class HashChainLedger:
    """哈希链账本 — 每条消息链式累积, 篡改/丢消息可检测。

    entry = {
        "seq": int,              # 本链序号 (0 起)
        "ts": str,               # ISO 时间戳
        "sender": str,           # 发送方标识 (machine/profile)
        "msg_id": str,           # 消息唯一 ID
        "kind": str,             # 消息类型 (dm/broadcast/task/team_memory/billing...)
        "prev_hash": str,        # 前一条 entry 的哈希 (链式)
        "payload_hash": str,     # payload 的 SHA256 (防篡改)
        "payload": Any,          # 消息内容 (可 JSON 序列化)
    }
    entry_hash = SHA256(canonical_json(entry 不含 payload 大字段? 不, 全量))
    """

    def __init__(self, entries: Optional[List[Dict]] = None):
        self._entries: List[Dict] = []
        if entries:
            self._entries = list(entries)

    # ── 追加 ──
    def append(self, sender: str, msg_id: str, payload: Any,
               kind: str = "message", ts: Optional[str] = None) -> Dict:
        prev_hash = self._entries[-1]["entry_hash"] if self._entries else ("0" * 64)
        entry = {
            "seq": len(self._entries),
            "ts": ts or time.strftime("%Y-%m-%dT%H:%M:%S.%fZ", time.gmtime()),
            "sender": sender,
            "msg_id": msg_id,
            "kind": kind,
            "prev_hash": prev_hash,
            "payload_hash": _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            "payload": payload,
        }
        entry["entry_hash"] = self._entry_hash(entry)
        self._entries.append(entry)
        return entry

    @staticmethod
    def _entry_hash(entry: Dict) -> str:
        """entry 的规范哈希 (排除自身 entry_hash 字段, 防止自引用)。"""
        core = {k: v for k, v in entry.items() if k != "entry_hash"}
        return _sha256(json.dumps(core, ensure_ascii=False, sort_keys=True, default=str))

    # ── 校验 ──
    def verify(self) -> Tuple[bool, Optional[int]]:
        """完整性校验: 返回 (是否完好, 首个损坏序号 or None)。

        - 任一 entry_hash 不匹配 → 篡改
        - prev_hash 不匹配 → 链断裂 (丢消息/乱序)
        """
        prev = "0" * 64
        for i, e in enumerate(self._entries):
            if e.get("prev_hash") != prev:
                return False, i
            if e.get("entry_hash") != self._entry_hash(e):
                return False, i
            prev = e["entry_hash"]
        return True, None

    def head_hash(self) -> str:
        """链头哈希 — 每日锚定用 (IPFS CID / 广播给其他节点)。"""
        return self._entries[-1]["entry_hash"] if self._entries else ("0" * 64)

    # ── 序列化 ──
    def to_list(self) -> List[Dict]:
        return [dict(e) for e in self._entries]

    def __len__(self):
        return len(self._entries)


class LocalJournal:
    """append-only 本地日志 (JSONL) — fsync 持久化, Redis 挂不丢。

    - 文件: {dir}/{name}.jsonl
    - append: 写入 + flush + fsync (崩溃安全)
    - 发送方/接收方各写一条 (sender=自己/对方), 完整可追溯
    """

    def __init__(self, name: str, journal_dir: Optional[Path] = None):
        self.name = name
        self.dir = Path(journal_dir or DEFAULT_JOURNAL_DIR)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{name}.jsonl"
        self._lock = threading.Lock()
        self._fh = open(self.path, "a", encoding="utf-8")

    def append(self, entry: Dict) -> None:
        with self._lock:
            self._fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()
            os.fsync(self._fh.fileno())

    def load(self) -> List[Dict]:
        if not self.path.exists():
            return []
        with self._lock:
            out = []
            for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue  # 容忍尾部不完整行 (崩溃残留)
            return out

    def close(self) -> None:
        with self._lock:
            try:
                self._fh.close()
            except Exception:
                pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class Web3MessagingLayer:
    """组合 HashChainLedger + LocalJournal 的消息记录层。

    用法:
        layer = Web3MessagingLayer("profile_a")
        layer.log_send("004/meshctx", "msg123", {"text": "hi"}, kind="dm")
        layer.log_receive("002/meshctx", "msg124", {"text": "hello"}, kind="dm")
        ok, bad = layer.verify()          # 完整性校验
        head = layer.head_hash()          # 链头 (锚定/广播)
        recovered = layer.load_journal()  # Redis 挂后从本地重建
    """

    def __init__(self, name: str, journal_dir: Optional[Path] = None):
        self.name = name
        self.journal = LocalJournal(name, journal_dir)
        self.ledger = HashChainLedger()
        # 从既有 journal 恢复链 (重启/Redis 挂后)
        for e in self.journal.load():
            try:
                self.ledger.append(
                    sender=e.get("sender", "?"),
                    msg_id=e.get("msg_id", f"recovered-{e.get('seq')}"),
                    payload=e.get("payload", {}),
                    kind=e.get("kind", "message"),
                    ts=e.get("ts"),
                )
            except Exception:
                pass

    def _record(self, sender: str, msg_id: str, payload: Any, kind: str) -> Dict:
        entry = self.ledger.append(sender, msg_id, payload, kind=kind)
        self.journal.append(entry)
        return entry

    def log_send(self, sender: str, msg_id: str, payload: Any, kind: str = "message") -> Dict:
        """发送方记录 (发送前调用)。"""
        return self._record(f"{sender}>send", msg_id, payload, kind=kind)

    def log_receive(self, sender: str, msg_id: str, payload: Any, kind: str = "message") -> Dict:
        """接收方记录 (收到时调用)。"""
        return self._record(f"{sender}>recv", msg_id, payload, kind=kind)

    def verify(self) -> Tuple[bool, Optional[int]]:
        return self.ledger.verify()

    def head_hash(self) -> str:
        return self.ledger.head_hash()

    def load_journal(self) -> List[Dict]:
        """Redis 挂后从本地 journal 重建消息流。"""
        return self.journal.load()

    def stats(self) -> Dict:
        ok, bad = self.verify()
        return {
            "name": self.name,
            "entries": len(self.ledger),
            "journal_path": str(self.journal.path),
            "verified": ok,
            "first_bad": bad,
            "head_hash": self.head_hash(),
        }
