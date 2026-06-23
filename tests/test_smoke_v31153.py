"""
smoke test for meshctx v3.115.3 — validates bug fixes.
Validates: PluginManager.list_all(), list_active(), HealthMonitor.check_all(), get_health_monitor()
"""
import sys, asyncio, json

def test_plugin_manager_list_all():
    """BUG#3 fix: PluginManager.list_all() must return list, not _P proxy"""
    from src.core.kernel import get_kernel
    k = get_kernel()
    
    # Empty kernel has no plugins registered yet
    result = k.plugins.list_all()
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    # result is empty because no plugins registered
    
    # Register a concrete plugin and verify
    from src.core.kernel import PluginInfo, PluginState
    class TestPlugin:
        info = PluginInfo(name="test_plugin", version="1.0", description="test")
        state = PluginState.LOADED
    plugin = TestPlugin()
    k.plugins.register(plugin)
    
    result2 = k.plugins.list_all()
    assert isinstance(result2, list), f"Expected list after register, got {type(result2)}"
    assert len(result2) >= 1, f"Expected at least 1 plugin, got {len(result2)}"
    assert any(p["name"] == "test_plugin" for p in result2), "test_plugin not in list_all"
    
    # Verify structure
    for p in result2:
        assert "name" in p, f"Missing 'name' in {p}"
        assert "version" in p, f"Missing 'version' in {p}"
        assert "state" in p, f"Missing 'state' in {p}"
    
    print("  ✅ test_plugin_manager_list_all")

def test_plugin_manager_list_active():
    """BUG#1 fix: PluginManager.list_active() must return list, not _P proxy"""
    from src.core.kernel import get_kernel
    k = get_kernel()
    
    result = k.plugins.list_active()
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    # All plugins start LOADED (not ACTIVE), so list_active should be empty or have ACTIVE ones
    
    print("  ✅ test_plugin_manager_list_active")

def test_health_monitor_get():
    """BUG#4 fix: get_health_monitor() must exist and return RealtimeHealthMonitor"""
    from src.core.health_monitor import get_health_monitor, RealtimeHealthMonitor
    
    hm = get_health_monitor()
    assert isinstance(hm, RealtimeHealthMonitor), f"Expected RealtimeHealthMonitor, got {type(hm)}"
    
    # Singleton check
    hm2 = get_health_monitor()
    assert hm is hm2, "get_health_monitor() should return singleton"
    
    print("  ✅ test_health_monitor_get")

def test_health_monitor_check_all():
    """BUG#2 fix: check_all() must return proper dict with ok/total/error keys"""
    from src.core.health_monitor import get_health_monitor
    
    hm = get_health_monitor()
    result = asyncio.run(hm.check_all())
    
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "ok" in result, "Missing 'ok' key"
    assert "total" in result, "Missing 'total' key"
    assert "error" in result, "Missing 'error' key"
    assert "errors" in result, "Missing 'errors' key"
    assert "modules" in result, "Missing 'modules' key"
    
    assert result["ok"] == result["total"] - result["error"], f"ok != total - error: {result}"
    assert result["total"] == 3, f"Expected 3 modules, got {result['total']}"
    assert result["error"] == 0, f"Expected 0 errors, got {result['error']}"
    
    # Module structure
    assert "kernel" in result["modules"]
    assert "event_bus" in result["modules"]
    assert "gateway" in result["modules"]
    for name, mod in result["modules"].items():
        assert "ok" in mod, f"Module {name} missing 'ok'"
        assert "latency_ms" in mod, f"Module {name} missing 'latency_ms'"
    
    print("  ✅ test_health_monitor_check_all")

def test_json_serializable():
    """Verify that all return values from fixed methods are JSON-serializable"""
    from src.core.kernel import get_kernel
    from src.core.health_monitor import get_health_monitor
    
    k = get_kernel()
    hm = get_health_monitor()
    
    # These should NOT raise TypeError
    json.dumps(k.plugins.list_all())
    json.dumps(k.plugins.list_active())
    json.dumps(asyncio.run(hm.check_all()))
    
    print("  ✅ test_json_serializable")

def test_getattr_not_leaking():
    """Verify __getattr__ doesn't silently mask missing methods"""
    from src.core.health_monitor import get_health_monitor
    
    hm = get_health_monitor()
    
    # check_all() should exist as a real method, not via __getattr__
    assert hasattr(hm, "check_all"), "check_all() should exist"
    
    # Accessing a genuinely non-existent attribute should still work via _P
    # but we want to ensure check_all is NOT going through __getattr__
    import inspect
    check_all_method = getattr(type(hm), "check_all", None)
    assert check_all_method is not None, "check_all should be a class method on RealtimeHealthMonitor"
    
    print("  ✅ test_getattr_not_leaking")

if __name__ == "__main__":
    print("╔══════════════════════════════════════════════╗")
    print("║  meshctx v3.115.3 Smoke Test Suite          ║")
    print("╚══════════════════════════════════════════════╝")
    
    tests = [
        ("PluginManager.list_all() → list", test_plugin_manager_list_all),
        ("PluginManager.list_active() → list", test_plugin_manager_list_active),
        ("get_health_monitor() exists", test_health_monitor_get),
        ("HealthMonitor.check_all() → dict", test_health_monitor_check_all),
        ("JSON serializable returns", test_json_serializable),
        ("__getattr__ not masking real methods", test_getattr_not_leaking),
    ]
    
    passed = 0
    failed = 0
    
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  ❌ {name}: {e}")
    
    print(f"\n{'='*50}")
    print(f"  Results: {passed} passed, {failed} failed, {passed+failed} total")
    print(f"{'='*50}")
    
    if failed > 0:
        sys.exit(1)
