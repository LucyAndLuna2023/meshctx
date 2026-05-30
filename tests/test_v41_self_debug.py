"""v3.41 Self-Debug Engine tests"""
import pytest, sys, io

class TestErrorCapture:
    def test_capture_module_not_found(self):
        from src.core.self_debug import ErrorCapture
        c = ErrorCapture('ModuleNotFoundError', "No module named 'test'", '', 'test.py', 10)
        assert c.error_type == 'ModuleNotFoundError'
        assert c.module == 'test.py'
        assert c.line == 10

class TestRootCauseAnalyzer:
    def test_module_not_found(self):
        from src.core.self_debug import RootCauseAnalyzer, ErrorCapture
        a = RootCauseAnalyzer()
        c = ErrorCapture('ModuleNotFoundError', "No module named 'numpy'", '', 'main.py', 5)
        r = a.analyze(c)
        assert r['error_type'] == 'ModuleNotFoundError'
        assert len(r['root_causes']) > 0
        assert len(r['suggested_fixes']) > 0
    
    def test_attribute_error(self):
        from src.core.self_debug import RootCauseAnalyzer, ErrorCapture
        a = RootCauseAnalyzer()
        c = ErrorCapture('AttributeError', "object has no attribute 'foo'", '', 'test.py', 1)
        r = a.analyze(c)
        assert r['error_type'] == 'AttributeError'
    
    def test_type_error(self):
        from src.core.self_debug import RootCauseAnalyzer, ErrorCapture
        a = RootCauseAnalyzer()
        c = ErrorCapture('TypeError', "unexpected keyword argument 'name'", '', 'test.py', 1)
        r = a.analyze(c)
        assert r['error_type'] == 'TypeError'
    
    def test_unknown_error(self):
        from src.core.self_debug import RootCauseAnalyzer, ErrorCapture
        a = RootCauseAnalyzer()
        c = ErrorCapture('SomeWeirdError', "something happened", '', '', 0)
        r = a.analyze(c)
        assert 'unknown' in r['root_causes'][0]['cause']

class TestFixGenerator:
    def test_module_not_found_fix(self):
        from src.core.self_debug import FixGenerator, ErrorCapture, RootCauseAnalyzer
        g = FixGenerator()
        a = RootCauseAnalyzer()
        c = ErrorCapture('ModuleNotFoundError', "No module named 'requests'", '', '', 0)
        analysis = a.analyze(c)
        fixes = g.generate(c, analysis)
        assert len(fixes) > 0
        assert any('install' in str(f) for f in fixes)
    
    def test_typeerror_kwargs_fix(self):
        from src.core.self_debug import FixGenerator, ErrorCapture, RootCauseAnalyzer
        g = FixGenerator()
        a = RootCauseAnalyzer()
        c = ErrorCapture('TypeError', "got an unexpected keyword argument 'test'", '', '', 0)
        analysis = a.analyze(c)
        fixes = g.generate(c, analysis)
        assert any('kwargs' in str(f).lower() for f in fixes)

class TestSelfDebugEngine:
    def test_full_debug_cycle(self):
        from src.core.self_debug import SelfDebugEngine
        engine = SelfDebugEngine()
        try:
            raise ModuleNotFoundError("No module named 'test_module'")
        except ModuleNotFoundError:
            result = engine.debug(*sys.exc_info())
            assert result.phase.value in ['analyze', 'generate']
            assert result.duration_ms > 0
    
    def test_capture_from_exception(self):
        from src.core.self_debug import SelfDebugEngine
        engine = SelfDebugEngine()
        try:
            {}['nonexistent']
        except KeyError:
            capture = engine.capture(*sys.exc_info())
            assert capture.error_type == 'KeyError'
    
    def test_get_stats(self):
        from src.core.self_debug import SelfDebugEngine
        engine = SelfDebugEngine()
        stats = engine.get_stats()
        assert 'total_errors' in stats
        assert 'auto_fixed' in stats
        assert 'fix_rate' in stats
    
    def test_dangerous_fix_not_auto_applied(self):
        from src.core.self_debug import SelfDebugEngine
        engine = SelfDebugEngine()
        # A fix with "rm -rf" should never be auto-applied
        assert not engine.evaluate_fix({'strategy': 'execute', 'command': 'rm -rf /tmp', 'confidence': 0.99})
    
    def test_high_confidence_fix_auto_applied(self):
        from src.core.self_debug import SelfDebugEngine
        engine = SelfDebugEngine()
        assert engine.evaluate_fix({'strategy': 'add_kwargs', 'confidence': 0.9})
    
    def test_low_confidence_not_applied(self):
        from src.core.self_debug import SelfDebugEngine
        engine = SelfDebugEngine()
        assert not engine.evaluate_fix({'strategy': 'log_and_skip', 'confidence': 0.4})
    
    def test_history_accumulates(self):
        from src.core.self_debug import SelfDebugEngine
        engine = SelfDebugEngine()
        before = len(engine.history)
        try: raise ValueError("test")
        except ValueError:
            engine.debug(*sys.exc_info())
        assert len(engine.history) > before
