"""v3.74 Sandbox v2 — tests"""
import pytest
from src.core.sandbox import CodeSandboxV2, SandboxResult, get_sandbox

class TestSandbox:
    def test_python(self):
        s = CodeSandboxV2()
        r = s.run_python("print('hello')")
        assert "hello" in r.output; assert r.exit_code == 0

    def test_python_error(self):
        s = CodeSandboxV2()
        r = s.run_python("1/0")
        assert r.exit_code != 0

    def test_bash(self):
        s = CodeSandboxV2()
        r = s.run_bash("echo hi")
        assert "hi" in r.output

    def test_timeout(self):
        s = CodeSandboxV2(timeout=1)
        r = s.run_python("import time; time.sleep(10)")
        assert "TIMEOUT" in r.error

    def test_singleton(self):
        assert get_sandbox() is get_sandbox()
