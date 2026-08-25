"""
meshctx Heartbeat — 心跳监控 (开源真实实现)
============================================
对标: OpenClaw heartbeat。

- heartbeat_start: 启动心跳监控 (后台守护线程 + 计时器)
- heartbeat_ping:  发送心跳 (重置计时器 / 清零 miss 计数)
- heartbeat_status: 查询心跳状态 (单个或全部)
- heartbeat_stop:  停止心跳监控

多实例管理: dict + threading.Lock, 支持任意数量的命名心跳。
不再依赖 meshctx-core 私有仓库。
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("meshctx.heartbeat")

# 心跳状态目录 (保留用于持久化扩展; 运行时状态保存在内存 dict)
HB_DIR = Path.home() / ".meshctx" / "heartbeats"

_hb_lock = threading.RLock()
_heartbeats: Dict[str, dict] = {}


def _status_dict(name: str, record: dict) -> dict:
    now = time.time()
    last_ping = record.get("last_ping", 0.0)
    return {
        "name": name,
        "status": record.get("status", "unknown"),
        "interval_seconds": record.get("interval", 60),
        "last_ping": last_ping,
        "age_seconds": round(now - last_ping, 1) if last_ping else None,
        "misses": record.get("misses", 0),
        "max_misses": record.get("max_misses", 3),
        "started_at": record.get("started_at"),
    }


def _monitor_loop(name: str):
    """心跳守护线程: 每个 interval 检查一次, 超时累计 miss, 达阈值触发 on_miss。"""
    record = _heartbeats.get(name)
    if record is None:
        return
    interval = float(record.get("interval", 60))
    while True:
        with _hb_lock:
            if record.get("status") != "running":
                return
            last_ping = record.get("last_ping", 0.0)
        # 分段睡眠, 便于 stop() 及时退出
        deadline = time.time() + interval
        while time.time() < deadline:
            time.sleep(min(0.5, max(0.05, deadline - time.time())))
            with _hb_lock:
                if record.get("status") != "running":
                    return
        with _hb_lock:
            if record.get("status") != "running":
                return
            if time.time() - record.get("last_ping", 0.0) >= interval:
                record["misses"] = record.get("misses", 0) + 1
                misses = record["misses"]
                max_misses = int(record.get("max_misses", 3))
                on_miss = record.get("on_miss")
            else:
                continue
        if misses >= max_misses:
            with _hb_lock:
                record["status"] = "dead"
            logger.warning("[heartbeat] %s 心跳超时 (连续 miss %d/%d)",
                           name, misses, max_misses)
            if callable(on_miss):
                try:
                    on_miss(name, _status_dict(name, record))
                except Exception as e:  # noqa: BLE001
                    logger.warning("[heartbeat] %s on_miss 回调失败: %s", name, e)
            return


def heartbeat_start(name: str, interval_seconds: int = 60,
                    on_miss: Callable = None, max_misses: int = 3) -> dict:
    """启动心跳监控。

    Args:
        name: 心跳唯一名称 (同名的已运行心跳会被替换为新的)。
        interval_seconds: 检测间隔 (秒), 超过该间隔未 ping 记 1 次 miss。
        on_miss: 可选回调, 连续 miss 达到 max_misses 时调用
                 ``on_miss(name, status_dict)``。
        max_misses: 允许的最大连续 miss 数, 超过后心跳标记为 dead。

    Returns:
        dict: 心跳状态。
    """
    if not name or not isinstance(name, str):
        raise ValueError("heartbeat name 必须是非空字符串")
    interval = max(1, int(interval_seconds))
    max_misses = max(1, int(max_misses))
    with _hb_lock:
        record = {
            "name": name,
            "interval": interval,
            "max_misses": max_misses,
            "misses": 0,
            "last_ping": time.time(),
            "started_at": time.time(),
            "status": "running",
            "on_miss": on_miss,
            "thread": None,
        }
        _heartbeats[name] = record
        thread = threading.Thread(
            target=_monitor_loop, args=(name,),
            name=f"meshctx-heartbeat-{name}", daemon=True,
        )
        record["thread"] = thread
        thread.start()
    logger.info("[heartbeat] %s 启动 (interval=%ss, max_misses=%d)",
                name, interval, max_misses)
    return _status_dict(name, record)


def heartbeat_ping(name: str) -> dict:
    """发送心跳 (重置计时器 / miss 计数清零)。"""
    with _hb_lock:
        record = _heartbeats.get(name)
        if record is None:
            return {"name": name, "status": "unknown",
                    "error": "heartbeat 未启动, 请先调用 heartbeat_start"}
        record["last_ping"] = time.time()
        record["misses"] = 0
        if record.get("status") in ("running", "dead"):
            record["status"] = "running"
        return _status_dict(name, record)


def heartbeat_status(name: str = None) -> dict:
    """查看心跳状态。

    Args:
        name: 心跳名称; 为 None 时返回所有心跳的汇总。

    Returns:
        dict: 单个心跳的状态, 或 {"count": n, "heartbeats": [...]} 汇总。
    """
    with _hb_lock:
        if name is not None:
            record = _heartbeats.get(name)
            if record is None:
                return {"name": name, "status": "unknown",
                        "error": "heartbeat 未启动"}
            return _status_dict(name, record)
        entries = [_status_dict(n, r) for n, r in _heartbeats.items()]
        return {"count": len(entries), "heartbeats": entries}


def heartbeat_stop(name: str) -> dict:
    """停止心跳监控 (守护线程将在下一个检查点退出)。"""
    with _hb_lock:
        record = _heartbeats.get(name)
        if record is None:
            return {"name": name, "status": "unknown",
                    "error": "heartbeat 未启动"}
        record["status"] = "stopped"
        thread = record.get("thread")
    if thread is not None and thread.is_alive():
        thread.join(timeout=max(2.0, float(record.get("interval", 60)) + 1.0))
    with _hb_lock:
        record["status"] = "stopped"
        record["thread"] = None
    logger.info("[heartbeat] %s 已停止", name)
    return _status_dict(name, record)


__all__ = ["heartbeat_start", "heartbeat_ping", "heartbeat_status", "heartbeat_stop"]
