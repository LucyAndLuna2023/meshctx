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


def _canonical_json(obj: Any) -> str:
    """JSON 规范化: 先 roundtrip (json.dumps→loads) 再 sort_keys dump。

    P3 (002meshctx 审计): 直接 json.dumps(default=str) 对 datetime 等对象
    跨环境不稳定; roundtrip 后保证跨环境一致。
    """
    try:
        obj = json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        obj = str(obj)
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


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
        # P2 (002meshctx 审计): 加锁防并发 seq 竞态
        self._lock = threading.Lock()
        if entries:
            self._entries = list(entries)

    # ── 追加 ──
    def append(self, sender: str, msg_id: str, payload: Any,
               kind: str = "message", ts: Optional[str] = None) -> Dict:
        with self._lock:
            prev_hash = self._entries[-1]["entry_hash"] if self._entries else ("0" * 64)
            entry = {
                "seq": len(self._entries),
                "ts": ts or time.strftime("%Y-%m-%dT%H:%M:%S.%fZ", time.gmtime()),
                "sender": sender,
                "msg_id": msg_id,
                "kind": kind,
                "prev_hash": prev_hash,
                "payload_hash": _sha256(_canonical_json(payload)),
                "payload": payload,
            }
            entry["entry_hash"] = self._entry_hash(entry)
            self._entries.append(entry)
            return entry

    def restore(self, entry: Dict) -> bool:
        """直接载入原始 entry (保留原 seq/prev_hash/entry_hash, 勿重算)。

        P1 (002meshctx 审计): 此前 __init__ 用 append 重建链 (重编号 seq/重算
        prev_hash), 恢复时删中间行会自我一致 → verify=True 检测不出丢消息。
        修复: 恢复时载入原始 entry, 中间断裂即 prev_hash 不匹配 → verify 检出。
        返回是否成功载入 (校验该 entry 自洽)。
        """
        with self._lock:
            if not isinstance(entry, dict) or "entry_hash" not in entry:
                return False
            # 校验 entry 自身哈希一致 (防篡改)
            if entry.get("entry_hash") != self._entry_hash(entry):
                return False
            self._entries.append(dict(entry))
            return True

    @staticmethod
    def _entry_hash(entry: Dict) -> str:
        """entry 的规范哈希 (排除自身 entry_hash 字段, 防止自引用)。

        P3 (002meshctx 审计): 用 _canonical_json (JSON roundtrip) 保证跨环境稳定,
        不用 json.dumps(default=str) (datetime 等对象跨环境不一致)。
        """
        core = {k: v for k, v in entry.items() if k != "entry_hash"}
        return _sha256(_canonical_json(core))

    # ── 校验 ──
    def verify(self) -> Tuple[bool, Optional[int]]:
        """完整性校验: 返回 (是否完好, 首个损坏序号 or None)。

        - 任一 entry_hash 不匹配 → 篡改
        - prev_hash 不匹配 → 链断裂 (丢消息/乱序)
        """
        with self._lock:
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
        # P3 (002meshctx 审计): journal 含全量消息 payload, 必须 0600
        try:
            if self.path.exists():
                os.chmod(self.path, 0o600)
        except Exception:
            pass
        self._fh = open(self.path, "a", encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except Exception:
            pass

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
        # P1 (002meshctx 审计): 恢复时载入原始 entry (保留 seq/prev_hash/entry_hash),
        # 不再 append 重算 — 中间断裂可被 verify 检出
        for e in self.journal.load():
            try:
                self.ledger.restore(e)
            except Exception:
                continue

    def _record(self, sender: str, msg_id: str, payload: Any, kind: str) -> Dict:
        # P2 (002meshctx 审计): 原子性 — 先写盘成功再入链, 防磁盘满时内存/磁盘不一致。
        # entry 由 ledger.append 生成 (含哈希), 若 journal.append 失败则不入链 (回滚)。
        entry = self.ledger.append(sender, msg_id, payload, kind=kind)
        try:
            self.journal.append(entry)
        except Exception:
            # 写盘失败: 从链中移除刚追加的 entry, 保持一致
            self.ledger._entries.pop()
            raise
        # P3-1: 链头落独立文件 (外部对比可检出尾部截断)
        self.persist_head()
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

    def persist_head(self) -> str:
        """P3-1 (002codex 审计): 链头哈希落独立文件。

        尾部截断 (append-only 固有限制) 无法被 verify 检出, 但每次记录后
        把 head_hash 写入独立 .head 文件 — 外部对比可检出"日志被截尾"。
        返回当前 head_hash。
        """
        h = self.head_hash()
        try:
            self.journal.dir.mkdir(parents=True, exist_ok=True)
            _p = self.journal.dir / f"{self.name}.head"
            with open(_p, "w", encoding="utf-8") as f:
                f.write(h + "\n")
            try:
                os.chmod(_p, 0o600)
            except Exception:
                pass
        except Exception:
            pass
        return h

    def load_journal(self) -> List[Dict]:
        """Redis 挂后从本地 journal 重建消息流。"""
        return self.journal.load()

    def stats(self) -> Dict:
        ok, bad = self.verify()
        # 对比本地 head 文件 (若存在) — 检出尾部截断
        _head_file = self.journal.dir / f"{self.name}.head"
        _head_mismatch = False
        try:
            if _head_file.exists():
                _saved = _head_file.read_text(encoding="utf-8").strip()
                _cur = self.head_hash()
                if _saved and _saved != _cur:
                    _head_mismatch = True
        except Exception:
            pass
        return {
            "name": self.name,
            "entries": len(self.ledger),
            "journal_path": str(self.journal.path),
            "verified": ok,
            "first_bad": bad,
            "head_hash": self.head_hash(),
            "head_file_mismatch": _head_mismatch,  # True=日志被截尾/外部篡改
        }
