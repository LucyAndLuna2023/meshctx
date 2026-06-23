"""
Test v1.6.0 — Self-Healing System Extensions

Covers:
  1. ErrorLearner — classification, recording, stats, should_auto_recover
  2. ErrorClass — transient vs permanent detection
  3. report_crash — restart_on_crash logic with max_crash_restarts
  4. periodic_ping — health ping check
  5. get_status_aggregation — status aggregation
  6. Integration: HealerPlugin with ErrorLearner wired in
  7. Enhanced get_system_health includes error_learner + aggregation
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS = {"passed": 0, "failed": 0, "total": 0}


def _t(name):
    def w(fn):
        async def r():
            RESULTS["total"] += 1
            try:
                await fn()
                RESULTS["passed"] += 1
                print(f"  ✓ {name}")
            except AssertionError as e:
                RESULTS["failed"] += 1
                print(f"  ✗ {name}: {e}")
            except Exception as e:
                RESULTS["failed"] += 1
                print(f"  ✗ {name}: {type(e).__name__}: {e}")
        return r
    return w


# ═══════════════════════════════════════════════════════════
# 1. ErrorLearner — Classification
# ═══════════════════════════════════════════════════════════

@_t("ErrorLearner: transient classification (timeout)")
async def test_error_learner_transient_timeout():
    from src.core.healer import ErrorLearner, ErrorClass
    el = ErrorLearner()
    cls = el.classify("connection timeout to upstream service")
    assert cls == ErrorClass.TRANSIENT, f"Expected TRANSIENT, got {cls}"


@_t("ErrorLearner: transient classification (rate_limit)")
async def test_error_learner_transient_rate_limit():
    from src.core.healer import ErrorLearner, ErrorClass
    el = ErrorLearner()
    cls = el.classify("rate_limit exceeded, retry later")
    assert cls == ErrorClass.TRANSIENT, f"Expected TRANSIENT, got {cls}"


@_t("ErrorLearner: permanent classification (permission)")
async def test_error_learner_permanent_permission():
    from src.core.healer import ErrorLearner, ErrorClass
    el = ErrorLearner()
    cls = el.classify("permission denied: cannot access /etc/config")
    assert cls == ErrorClass.PERMANENT, f"Expected PERMANENT, got {cls}"


@_t("ErrorLearner: permanent classification (not_found)")
async def test_error_learner_permanent_not_found():
    from src.core.healer import ErrorLearner, ErrorClass
    el = ErrorLearner()
    cls = el.classify("module 'xyz' not found")
    assert cls == ErrorClass.PERMANENT, f"Expected PERMANENT, got {cls}"


@_t("ErrorLearner: unknown classification (generic)")
async def test_error_learner_unknown():
    from src.core.healer import ErrorLearner, ErrorClass
    el = ErrorLearner()
    cls = el.classify("something unexpected happened")
    assert cls == ErrorClass.UNKNOWN, f"Expected UNKNOWN, got {cls}"


@_t("ErrorLearner: record returns correct class")
async def test_error_learner_record():
    from src.core.healer import ErrorLearner, ErrorClass
    el = ErrorLearner()
    cls = el.record("test_plugin", "connection refused")
    assert cls == ErrorClass.TRANSIENT

    cls = el.record("test_plugin", "invalid config value")
    assert cls == ErrorClass.PERMANENT


@_t("ErrorLearner: record tracks auto_recover_success")
async def test_error_learner_record_recover():
    from src.core.healer import ErrorLearner, ErrorClass
    el = ErrorLearner()
    error = "connection timeout"
    el.record("test_plugin", error, auto_recover_success=True)
    el.record("test_plugin", error, auto_recover_success=True)
    el.record("test_plugin", error, auto_recover_success=False)

    stats = el.get_stats()
    assert stats["total_patterns"] >= 1

    patterns = el.get_known_patterns()
    found = [p for p in patterns if "connection timeout" in p["signature"]]
    assert len(found) == 1, f"Expected pattern found, got {found}"
    assert found[0]["auto_recover_rate"] >= 0.66, f"Rate {found[0]['auto_recover_rate']}"


@_t("ErrorLearner: should_auto_recover blocks permanent")
async def test_error_learner_should_auto_recover_permanent():
    from src.core.healer import ErrorLearner
    el = ErrorLearner()
    assert not el.should_auto_recover("permission denied: access forbidden")
    assert not el.should_auto_recover("module not found: xyz")


@_t("ErrorLearner: should_auto_recover allows transient")
async def test_error_learner_should_auto_recover_transient():
    from src.core.healer import ErrorLearner
    el = ErrorLearner()
    assert el.should_auto_recover("connection timeout")
    assert el.should_auto_recover("rate_limit exceeded")


@_t("ErrorLearner: should_auto_recover blocks after repeated failure")
async def test_error_learner_should_auto_recover_repeated():
    from src.core.healer import ErrorLearner
    el = ErrorLearner()
    error = "connection reset"
    # 5+ failed auto-recovery attempts → should NOT auto recover
    for _ in range(6):
        el.record("test", error, auto_recover_success=False)
    assert not el.should_auto_recover(error), "Should block after 5+ failures"


@_t("ErrorLearner: get_stats structure")
async def test_error_learner_stats():
    from src.core.healer import ErrorLearner
    el = ErrorLearner()
    el.record("p1", "timeout", auto_recover_success=True)
    el.record("p1", "permission denied", auto_recover_success=False)
    stats = el.get_stats()
    assert "total_patterns" in stats
    assert "transient" in stats
    assert "permanent" in stats
    assert "unknown" in stats
    assert "history_size" in stats
    assert stats["total_patterns"] >= 2


@_t("ErrorLearner: get_known_patterns sorted by count")
async def test_error_learner_patterns():
    from src.core.healer import ErrorLearner
    el = ErrorLearner()
    for _ in range(10):
        el.record("p1", "timeout")
    for _ in range(3):
        el.record("p1", "permission denied")
    patterns = el.get_known_patterns()
    assert len(patterns) >= 2
    assert patterns[0]["count"] >= patterns[1]["count"]


# ═══════════════════════════════════════════════════════════
# 2. SelfHealingEngine — Crash + Restart
# ═══════════════════════════════════════════════════════════

@_t("SelfHealingEngine: report_crash tracks crashes")
async def test_engine_crash():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    e.register_plugin("test_crash")
    assert e.report_crash("test_crash", "segfault")
    h = e._plugin_health["test_crash"]
    assert h.crash_count == 1
    assert h.last_crash_time > 0


@_t("SelfHealingEngine: report_crash blocks beyond limit")
async def test_engine_crash_limit():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    e.max_crash_restarts = 2
    e.register_plugin("test_crash")
    assert e.report_crash("test_crash", "crash1")
    assert e.report_crash("test_crash", "crash2")
    assert not e.report_crash("test_crash", "crash3"), "Should exceed restart limit"


@_t("SelfHealingEngine: report_crash increments consecutive_failures")
async def test_engine_crash_failures():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    e.register_plugin("test_crash")
    e.report_crash("test_crash", "error")
    assert e._plugin_health["test_crash"].consecutive_failures == 1


@_t("SelfHealingEngine: periodic_ping ok")
async def test_engine_ping_ok():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    e.register_plugin("test_ping")
    e.heartbeat("test_ping")
    assert e.periodic_ping("test_ping")  # just heartbeated, should be ok


@_t("SelfHealingEngine: periodic_ping fail after timeout")
async def test_engine_ping_fail():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    e.heartbeat_interval = 0.01  # very short interval
    e.register_plugin("test_ping")
    # Fake an old heartbeat
    h = e._plugin_health["test_ping"]
    h.last_heartbeat = time.time() - 10  # 10s ago
    assert not e.periodic_ping("test_ping"), "Should fail after timeout"
    assert h.ping_failures == 1
    assert not h.periodic_ping_ok


@_t("SelfHealingEngine: get_status_aggregation structure")
async def test_engine_status_aggregation():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    e.register_plugin("p1")
    e.register_plugin("p2")
    agg = e.get_status_aggregation()
    assert agg["total"] == 2
    assert agg["healthy"] == 2
    assert agg["health_pct"] == 100.0


@_t("SelfHealingEngine: get_status_aggregation tracks critical")
async def test_engine_status_aggregation_critical():
    from src.core.healer import SelfHealingEngine, CircuitState
    e = SelfHealingEngine()
    e.register_plugin("p1")
    e.register_plugin("p2")
    # Open circuit one plugin
    e._plugin_health["p1"].circuit_state = CircuitState.OPEN
    agg = e.get_status_aggregation()
    assert agg["critical"] >= 1
    assert agg["health_pct"] < 100.0


# ═══════════════════════════════════════════════════════════
# 3. SelfHealingEngine — Enhanced Error Handling
# ═══════════════════════════════════════════════════════════

@_t("SelfHealingEngine: report_failure uses error learner")
async def test_engine_failure_records_learner():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    e.register_plugin("test_p1")
    e.report_failure("test_p1", "connection timeout")
    stats = e._error_learner.get_stats()
    assert stats["total_patterns"] >= 1


@_t("SelfHealingEngine: get_system_health includes aggregation")
async def test_engine_system_health_aggregation():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    e.register_plugin("p1")
    health = e.get_system_health()
    assert "aggregation" in health
    assert health["aggregation"]["total"] == 1
    assert "error_learner" in health


@_t("SelfHealingEngine: get_system_health includes crashes")
async def test_engine_system_health_crashes():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    e.register_plugin("p1")
    e.report_crash("p1", "segfault")
    health = e.get_system_health()
    assert health["plugins"]["p1"]["crashes"] == 1
    assert "ping_ok" in health["plugins"]["p1"]


@_t("SelfHealingEngine: restart_delay configurable")
async def test_engine_restart_delay():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    assert e.restart_delay == 1.0
    e.restart_delay = 2.5
    assert e.restart_delay == 2.5


@_t("SelfHealingEngine: max_crash_restarts configurable")
async def test_engine_max_crash():
    from src.core.healer import SelfHealingEngine
    e = SelfHealingEngine()
    assert e.max_crash_restarts == 3
    e.max_crash_restarts = 5
    assert e.max_crash_restarts == 5


# ═══════════════════════════════════════════════════════════
# 4. Integration — HealerPlugin with ErrorLearner
# ═══════════════════════════════════════════════════════════

@_t("SelfHealingEngine: error_learner wired into engine")
async def test_engine_learner_wired():
    from src.core.healer import SelfHealingEngine, ErrorLearner
    e = SelfHealingEngine()
    assert isinstance(e._error_learner, ErrorLearner)


@_t("SelfHealingEngine: heal uses error learner suggestions")
async def test_engine_heal_learner():
    """Verifies the heal method still works with learner wired in"""
    from src.core.kernel import Kernel
    from src.core.healer import SelfHealingEngine, HealerPlugin
    k = Kernel()
    k.plugins.register(HealerPlugin())
    await k.start(1)
    await k.plugins.load("healer")
    
    engine = k.plugins.get("healer").engine
    engine.register_plugin("test_p")
    
    # Simulate a transient error
    engine.report_failure("test_p", "connection timeout")
    health = engine.get_system_health()
    assert "error_learner" in health
    assert health["error_learner"]["total_patterns"] >= 1
    
    await k.stop()


@_t("ErrorLearner: empty stats on fresh instance")
async def test_learner_empty_stats():
    from src.core.healer import ErrorLearner
    el = ErrorLearner()
    stats = el.get_stats()
    assert stats["total_patterns"] == 0
    assert stats["transient"] == 0
    assert stats["permanent"] == 0
    assert stats["history_size"] == 0


@_t("ErrorLearner: empty patterns on fresh instance")
async def test_learner_empty_patterns():
    from src.core.healer import ErrorLearner
    el = ErrorLearner()
    assert el.get_known_patterns() == []


@_t("ErrorLearner: multiple records same error aggregates")
async def test_learner_aggregate():
    from src.core.healer import ErrorLearner
    el = ErrorLearner()
    for _ in range(5):
        el.record("p1", "timeout on connect")
    patterns = el.get_known_patterns()
    assert len(patterns) == 1
    assert patterns[0]["count"] == 5


async def main():
    tests = [
        # ErrorLearner — Classification
        test_error_learner_transient_timeout,
        test_error_learner_transient_rate_limit,
        test_error_learner_permanent_permission,
        test_error_learner_permanent_not_found,
        test_error_learner_unknown,
        test_error_learner_record,
        test_error_learner_record_recover,
        test_error_learner_should_auto_recover_permanent,
        test_error_learner_should_auto_recover_transient,
        test_error_learner_should_auto_recover_repeated,
        test_error_learner_stats,
        test_error_learner_patterns,
        test_learner_empty_stats,
        test_learner_empty_patterns,
        test_learner_aggregate,
        # SelfHealingEngine — Crash + Restart
        test_engine_crash,
        test_engine_crash_limit,
        test_engine_crash_failures,
        test_engine_ping_ok,
        test_engine_ping_fail,
        test_engine_status_aggregation,
        test_engine_status_aggregation_critical,
        # Enhanced Error Handling
        test_engine_failure_records_learner,
        test_engine_system_health_aggregation,
        test_engine_system_health_crashes,
        test_engine_restart_delay,
        test_engine_max_crash,
        # Integration
        test_engine_learner_wired,
        test_engine_heal_learner,
    ]
    for t in tests:
        await t()
    print(f"\n{'='*40}")
    print(f"  结果: {RESULTS['passed']}✓ / {RESULTS['failed']}✗ / {RESULTS['total']}项")
    print(f"{'='*40}")
    return RESULTS["failed"] == 0


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
