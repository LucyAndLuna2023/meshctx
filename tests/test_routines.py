"""WP6 (MCTX-PLAN-2026-0903) routines 例行值守核心测试。"""
import json
import time

import pytest

from src.core.routines import (CronMatcher, Routine, RoutineScheduler,
                               RoutineStore)


# ── CronMatcher ────────────────────────────────────────────────────────────
class TestCronMatcher:
    def test_star_matches_all(self):
        m = CronMatcher("* * * * *")
        assert m.match(0, 0, 1, 1, 0)
        assert m.match(59, 23, 28, 12, 6)

    def test_every_15_minutes(self):
        m = CronMatcher("*/15 * * * *")
        assert m.match(0, 5, 1, 1, 0)
        assert m.match(15, 5, 1, 1, 0)
        assert m.match(45, 5, 1, 1, 0)
        assert not m.match(7, 5, 1, 1, 0)

    def test_daily_0830(self):
        m = CronMatcher("30 8 * * *")
        assert m.match(30, 8, 3, 6, 2)
        assert not m.match(30, 7, 3, 6, 2)
        assert not m.match(29, 8, 3, 6, 2)

    def test_dom_or_dow(self):
        # 每月 1 号或周日
        m = CronMatcher("0 0 1 * 0")
        # 2026-09-01 是周二: dom 命中
        assert m.match(0, 0, 1, 9, 2)
        # 2026-09-06 是周日: dow 命中
        assert m.match(0, 0, 6, 9, 0)

    def test_next_after(self):
        m = CronMatcher("0 9 * * *")           # 每天 09:00
        import datetime
        ts = datetime.datetime(2026, 9, 3, 8, 0).timestamp()
        nxt = m.next_after(ts)
        assert nxt is not None
        lt = time.localtime(nxt)
        assert (lt.tm_hour, lt.tm_min) == (9, 0)
        assert nxt > ts

    def test_range_step_offset_standard(self):
        # P3 (三方同报): a-b/n 与 单值/n 步进从 range 起点起算 (标准 cron)
        m = CronMatcher("4/10 * * * *")
        assert m.match(4, 0, 1, 1, 0)
        assert m.match(14, 0, 1, 1, 0)
        assert m.match(24, 0, 1, 1, 0)
        assert not m.match(10, 0, 1, 1, 0)      # 旧实现错误命中 {10,20..}
        m2 = CronMatcher("1-10/3 * * * *")
        assert m2.match(1, 0, 1, 1, 0)
        assert m2.match(4, 0, 1, 1, 0)
        assert m2.match(7, 0, 1, 1, 0)
        assert m2.match(10, 0, 1, 1, 0)
        assert not m2.match(3, 0, 1, 1, 0)      # 旧实现错误命中 {3,6,9}
        m3 = CronMatcher("5-59/10 * * * *")
        assert m3.match(5, 0, 1, 1, 0) and m3.match(55, 0, 1, 1, 0)
        assert not m3.match(10, 0, 1, 1, 0)

    def test_invalid_field_count(self):
        with pytest.raises(ValueError):
            CronMatcher("* * * *")


# ── Routine 模型 ───────────────────────────────────────────────────────────
class TestRoutineModel:
    def test_interval_due_and_not(self):
        r = Routine(owner="local", prompt="打卡", kind="interval", schedule="60")
        r.created_at = time.time() - 120
        r.last_run = time.time() - 30
        assert not r.due(time.time())            # 距上次仅 30s < 60s
        r.last_run = time.time() - 61
        assert r.due(time.time())

    def test_first_run_waits_interval(self):
        r = Routine(owner="local", prompt="x", kind="interval", schedule="60")
        r.created_at = time.time() - 10          # 刚创建 10s
        assert not r.due(time.time())            # 不应创建即触发

    def test_cron_due(self):
        import datetime
        r = Routine(owner="local", prompt="x", kind="cron", schedule="0 9 * * *")
        now = datetime.datetime(2026, 9, 3, 9, 0, 30).timestamp()
        assert r.due(now)
        now2 = datetime.datetime(2026, 9, 3, 8, 0).timestamp()
        assert not r.due(now2)

    def test_render_template(self):
        import datetime
        r = Routine(owner="local", prompt="现在 {now} 日期 {date}", kind="interval",
                    schedule="3600")
        ts = datetime.datetime(2026, 9, 3, 14, 5).timestamp()
        out = r.render_prompt(ts)
        assert "14:05" in out and "2026-09-03" in out

    def test_roundtrip_dict(self):
        r = Routine(owner="o", prompt="p", name="n", kind="cron",
                    schedule="*/5 * * * *", enabled=False, max_rounds=3)
        r2 = Routine.from_dict(r.to_dict())
        assert r2.id == r.id and r2.kind == "cron" and r2.enabled is False
        assert r2.max_rounds == 3


# ── RoutineStore ───────────────────────────────────────────────────────────
class TestRoutineStore:
    def test_save_load_remove(self, tmp_path):
        st = RoutineStore(path=tmp_path / "r.json")
        r = Routine(owner="local", prompt="备份", kind="interval", schedule="86400")
        st.save(r)
        got = st.get(r.id)
        assert got is not None and got.prompt == "备份"
        lst = st.list()
        assert len(lst) == 1
        assert st.remove(r.id) is True
        assert st.remove(r.id) is False
        assert st.list() == []

    def test_atomic_no_tmp_left(self, tmp_path):
        st = RoutineStore(path=tmp_path / "r.json")
        for i in range(5):
            st.save(Routine(owner="o", prompt=f"p{i}"))
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []
        assert len(st.list()) == 5


# ── RoutineScheduler ───────────────────────────────────────────────────────
class TestRoutineScheduler:
    def _mk(self, tmp_path, clock, spawn):
        store = RoutineStore(path=tmp_path / "r.json")
        sched = RoutineScheduler(store=store, spawn_fn=spawn,
                                 tick_seconds=0.01, now_fn=clock)
        return store, sched

    def test_interval_fires_once_then_cooldown(self, tmp_path):
        now = [time.time()]
        fired = []

        def clock():
            return now[0]

        def spawn(r, t):
            fired.append((r.id, t))
            return True

        store, sched = self._mk(tmp_path, clock, spawn)
        try:
            r = Routine(owner="local", prompt="x", kind="interval", schedule="100")
            r.created_at = now[0] - 200          # 创建很久前
            store.save(r)
            sched.tick_now()
            assert len(fired) == 1               # 到期触发
            # 时间未过 interval → 不重复
            sched.tick_now()
            assert len(fired) == 1
            got = store.get(r.id)
            assert got.last_run == fired[0][1]   # 成功推进
            # 越过 interval → 再次触发
            now[0] += 150
            sched.tick_now()
            assert len(fired) == 2
        finally:
            sched.stop()

    def test_disabled_never_fires(self, tmp_path):
        fired = []

        def spawn(r, t):
            fired.append(r.id)
            return True

        store, sched = self._mk(tmp_path, lambda: time.time(), spawn)
        try:
            r = Routine(owner="o", prompt="x", kind="interval", schedule="10",
                        enabled=False)
            r.created_at = time.time() - 1000
            store.save(r)
            sched.tick_now()
            assert fired == []
        finally:
            sched.stop()

    def test_quota_fail_cooldown_no_last_run(self, tmp_path):
        now = [time.time()]

        def clock():
            return now[0]

        calls = []

        def spawn(r, t):
            calls.append(now[0])
            return False                          # 配额不足

        store, sched = self._mk(tmp_path, clock, spawn)
        try:
            r = Routine(owner="o", prompt="x", kind="interval", schedule="10")
            r.created_at = now[0] - 1000
            store.save(r)
            sched.tick_now()
            assert len(calls) == 1
            got = store.get(r.id)
            assert got.last_run == 0.0           # 失败不推进
            # 冷却期 (60s) 内不重试
            now[0] += 30
            sched.tick_now()
            assert len(calls) == 1
            # 冷却后重试
            from src.core.routines import FAILURE_COOLDOWN_SECONDS
            now[0] += FAILURE_COOLDOWN_SECONDS + 5
            sched.tick_now()
            assert len(calls) == 2
        finally:
            sched.stop()
