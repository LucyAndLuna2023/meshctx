#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Routines 例行值守 (WP6, MCTX-PLAN-2026-0903 P1-3) — 定时派活进 task_cards。

对位 Claude Code Routines: 定时/周期 → 自动 spawn 任务卡 (D2: task_cards 为统一
值守运行时, 复用 CardWorker 线程模型 / 配额 / 审批 / 恢复 / 审计 / 遥测 trace)。

设计:
- Routine: id / owner / name / kind(interval|cron) / schedule / prompt / enabled /
  last_run / created_at。磁盘 JSON (~/.meshctx/routines.json) 为真相源 (原子写)。
- CronMatcher: 5 字段子集 (* , a-b */n), minute 粒度。
- RoutineScheduler: 守护线程 tick (默认 5s), 到期经注入 spawn_fn 派活
  (配额/edition 语义由宿主 API 层决定 — 个人版定时值守开源; 事件值守/跨机=团队/企业)。
  幂等: last_run 成功才推进; 失败冷却 (默认 60s) 防 quota 打满时每 tick 空转。
- 旧 scheduler.py / channel_scheduler.py 双跑兼容, 删除点 = 3.124.0 (002codex P3)。
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("meshctx.routines")

ROUTINES_PATH = pathlib.Path.home() / ".meshctx" / "routines.json"

DEFAULT_TICK_SECONDS = 5.0
FAILURE_COOLDOWN_SECONDS = 60.0
MAX_TICK_JITTER = 0.5  # 防止多例行同秒齐射


def new_routine_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Cron 匹配 (5 字段子集, minute 粒度) ───────────────────────────────────
_FIELDS = ((0, 60), (0, 24), (1, 32), (1, 13), (0, 7))  # minute hour dom month dow
_NAMES = ("minute", "hour", "dom", "month", "dow")


def _parse_field(expr: str, lo: int, hi: int) -> Optional[set]:
    """'*' → None(任意); '*/n' / 'a-b' / 逗号列表 / 单值。非法返回 None 表示整字段任意? 
    返回 (set|None): None = 任意。'?' (dom/dow) 亦按任意处理。
    """
    expr = (expr or "*").strip()
    if expr in ("*", "?"):
        return None
    out = set()
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            if base == "*":
                start, end = lo, hi
            elif "-" in base:
                a, b = (int(x) for x in base.split("-", 1))
                start, end = a, b + 1
            else:                       # 单值起点 (标准 cron: 5/15 → 5,20,35,50)
                start, end = int(base), hi
            # 标准语义: 步进从 range 起点起算 (P3 三方同报: 原从 0 起算偏移)
            out.update(x for x in range(start, end) if (x - start) % step == 0)
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
            out.update(range(a, b + 1))
        else:
            out.add(int(part))
    # 校验越界
    for v in out:
        if not (lo <= v < hi):
            raise ValueError(f"cron 字段 {v} 越界 [{lo},{hi}) in {expr!r}")
    return out


class CronMatcher:
    """5 字段 cron 匹配器 (minute hour dom month dow; dow 0-6, 0=周日)。
    dom/dow: 两者均显式(非任意)时按"或"语义 (类标准 cron), 否则按指定者。"""

    def __init__(self, expr: str):
        parts = expr.split()
        if len(parts) != 5:
            raise ValueError(f"cron 需 5 字段: {expr!r}")
        self._sets: List[Optional[set]] = []
        for i, (p, (lo, hi)) in enumerate(zip(parts, _FIELDS)):
            self._sets.append(_parse_field(p, lo, hi))

    def match(self, minute: int, hour: int, dom: int, month: int, dow: int) -> bool:
        m, h, dom_set, mo, dow_set = self._sets   # 字段序: minute hour dom month dow
        if m is not None and minute not in m:
            return False
        if h is not None and hour not in h:
            return False
        if mo is not None and month not in mo:
            return False
        if dom_set is None and dow_set is None:
            return True
        if dom_set is None:
            return dow in dow_set
        if dow_set is None:
            return dom in dom_set
        return (dom in dom_set) or (dow in dow_set)   # dom/dow 或语义

    def next_after(self, ts: float, search_minutes: int = 525600) -> Optional[float]:
        """自 ts 起下一命中时刻 (分钟粒度); 一年内找不到返回 None。"""
        base = int(ts // 60) + 1
        for i in range(search_minutes):
            t = (base + i) * 60
            lt = time.localtime(t)
            if self.match(lt.tm_min, lt.tm_hour, lt.tm_mday, lt.tm_mon,
                          (lt.tm_wday + 1) % 7):          # 转 0-6, 0=周日
                return float(t)
        return None


# ── Routine 模型与存储 ────────────────────────────────────────────────────
@dataclass
class Routine:
    owner: str
    prompt: str                      # 派活 prompt (模板, {now} 可替换)
    name: str = ""
    kind: str = "interval"           # interval | cron
    schedule: str = "3600"           # interval: 秒; cron: 5 字段表达式
    enabled: bool = True
    title: str = ""
    model: str = ""
    max_rounds: int = 0
    wall_clock: float = 300.0
    plan: str = "free"               # 后台派活沿用创建时 plan (配额语义一致)
    last_run: float = 0.0
    last_status: str = ""            # ok | quota | error
    created_at: float = field(default_factory=time.time)
    id: str = field(default_factory=new_routine_id)

    def __post_init__(self):
        if not self.name:
            self.name = self.prompt[:40]
        if self.kind == "cron":
            self._matcher = CronMatcher(self.schedule)
        else:
            self._matcher = None
        try:
            self._interval = max(10, float(self.schedule))
        except (TypeError, ValueError):
            self._interval = 3600.0

    def render_prompt(self, now_ts: Optional[float] = None) -> str:
        """{now} / {date} 模板替换。"""
        now_ts = now_ts if now_ts is not None else time.time()
        lt = time.localtime(now_ts)
        return (self.prompt.replace("{now}", time.strftime("%H:%M", lt))
                .replace("{date}", time.strftime("%Y-%m-%d", lt)))

    def next_fire(self, now_ts: float, default_interval: float = 60.0) -> float:
        """计算下次应触发时间 (防同一例行重复触发)。"""
        if not self.enabled:
            return float("inf")
        if self.kind == "cron":
            minute_start = int(now_ts // 60) * 60
            lt = time.localtime(now_ts)
            if self._matcher.match(lt.tm_min, lt.tm_hour, lt.tm_mday, lt.tm_mon,
                                   (lt.tm_wday + 1) % 7):
                # 当前分钟命中: 本分钟已触发过 → 找下一命中; 否则即为应触发时刻
                if self.last_run >= minute_start:
                    nxt = self._matcher.next_after(now_ts)
                    return nxt if nxt is not None else float("inf")
                return float(minute_start)
            nxt = self._matcher.next_after(now_ts)
            return nxt if nxt is not None else float("inf")
        interval = getattr(self, "_interval", default_interval)
        base = self.last_run or self.created_at
        return base + interval

    def due(self, now_ts: float, default_interval: float = 60.0) -> bool:
        return self.enabled and self.next_fire(now_ts, default_interval) <= now_ts

    def to_dict(self) -> Dict[str, Any]:
        d = {k: getattr(self, k) for k in
             ("id", "owner", "name", "kind", "schedule", "prompt", "title", "model",
              "enabled", "last_run", "last_status", "created_at",
              "max_rounds", "wall_clock", "plan")}
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Routine":
        kws = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**kws)


class RoutineStore:
    """~/.meshctx/routines.json 原子落盘 (真相源)。跨线程/进程安全。"""

    def __init__(self, path: str | os.PathLike = ""):
        self._lock = threading.Lock()
        self._path = pathlib.Path(path) if path else ROUTINES_PATH

    def _load_all(self) -> Dict[str, Routine]:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                out = {}
                for r in data.get("routines", []):
                    try:
                        ro = Routine.from_dict(r)
                        out[ro.id] = ro
                    except Exception as e:
                        logger.warning("routine %s 解析失败: %s", r.get("id"), e)
                return out
        except Exception:
            logger.debug("routines load failed", exc_info=True)
        return {}

    def list(self) -> List[Routine]:
        with self._lock:
            return list(self._load_all().values())

    def get(self, rid: str) -> Optional[Routine]:
        with self._lock:
            return self._load_all().get(rid)

    def _atomic_write(self, routines: Dict[str, Routine]) -> None:
        payload = {"routines": [r.to_dict() for r in routines.values()]}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(
                f".{self._path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:
            logger.exception("routines atomic write failed")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def save(self, routine: Routine) -> Routine:
        with self._lock:
            all_r = self._load_all()
            all_r[routine.id] = routine
            self._atomic_write(all_r)
        return routine

    def remove(self, rid: str) -> bool:
        with self._lock:
            all_r = self._load_all()
            if rid not in all_r:
                return False
            del all_r[rid]
            self._atomic_write(all_r)
            return True

    def mark_fired(self, rid: str, ok: bool, note: str = "",
                   ts: Optional[float] = None) -> None:
        """成功推进 last_run; 失败仅记状态 (冷却由调度器处理)。ts 可注入 (测试假时钟)。
        P4-1 (002meshctx): last_run 只进不退 (max 防 PATCH/触发读改写竞态回退)。"""
        fired_at = ts if ts is not None else time.time()
        with self._lock:
            all_r = self._load_all()
            r = all_r.get(rid)
            if r is None:
                return
            if ok:
                r.last_run = max(fired_at, r.last_run)
            r.last_status = note or ("ok" if ok else "error")
            self._atomic_write(all_r)


# ── 调度线程 ──────────────────────────────────────────────────────────────
SpawnFn = Callable[[Routine, float], bool]     # 返回 True = 派活成功


class RoutineScheduler:
    """守护线程 tick: 到期例行 → spawn_fn (配额/enqueue 由宿主注入, API 层实现)。

    幂等: last_run 成功才推进; 失败进冷却 (默认 60s) 防空转打满日志。
    now_fn 可注入 (测试假时钟)。
    """

    def __init__(self, store: Optional[RoutineStore] = None,
                 spawn_fn: Optional[SpawnFn] = None,
                 tick_seconds: float = DEFAULT_TICK_SECONDS,
                 now_fn: Optional[Callable[[], float]] = None):
        self._store = store or RoutineStore()
        self._spawn_fn = spawn_fn
        self._tick = tick_seconds
        self._now = now_fn or time.time
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cooldown: Dict[str, float] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, name="meshctx-routines",
                                        daemon=True)
        self._thread.start()

    def stop(self, join_timeout: float = 2.0) -> None:
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=join_timeout)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                self._tick_once()
            except Exception:
                logger.exception("routines tick failed")
            self._stop_evt.wait(self._tick)

    def tick_now(self) -> List[str]:
        """同步执行一次检查 (测试用)。返回本次触发例行 id 列表。"""
        return self._tick_once()

    def _tick_once(self) -> List[str]:
        now = self._now()
        fired: List[str] = []
        if self._spawn_fn is None:
            return fired
        for r in self._store.list():
            if not r.enabled:
                continue
            if not r.due(now):
                continue
            if self._cooldown.get(r.id, 0.0) > now:
                continue
            try:
                ok = self._spawn_fn(r, now)
            except Exception as e:
                logger.warning("routine %s spawn 异常: %s", r.id, e)
                ok = False
            if ok:
                self._store.mark_fired(r.id, True, ts=now)
                self._cooldown.pop(r.id, None)
                fired.append(r.id)
                logger.info("routine %s fired (owner=%s)", r.id, r.owner)
            else:
                # 配额/失败 → 冷却, 稍后重试, 不推进 last_run
                self._store.mark_fired(r.id, False, note="retry", ts=now)
                self._cooldown[r.id] = now + FAILURE_COOLDOWN_SECONDS
        return fired


_default_scheduler: Optional[RoutineScheduler] = None


def get_routine_scheduler() -> RoutineScheduler:
    global _default_scheduler
    if _default_scheduler is None:
        _default_scheduler = RoutineScheduler()
    return _default_scheduler


def reset_routine_scheduler_for_tests():
    global _default_scheduler
    s = _default_scheduler
    if s is not None:
        s.stop()
    _default_scheduler = None


__all__ = [
    "Routine", "RoutineStore", "RoutineScheduler", "CronMatcher",
    "get_routine_scheduler", "reset_routine_scheduler_for_tests",
    "ROUTINES_PATH", "DEFAULT_TICK_SECONDS",
]
