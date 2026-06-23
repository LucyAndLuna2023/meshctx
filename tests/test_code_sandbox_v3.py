"""v3.97 Code Sandbox V3 — 8+ test cases for Docker isolation, multi-language, resource limits, audit logging."""
import json
import os
import sys
import tempfile

import pytest

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.code_sandbox_v3 import (
    CodeSandboxV3,
    CodeSandboxResult,
    SandboxLanguage,
    SandboxStatus,
    SandboxRiskLevel,
    AuditEntry,
    get_code_sandbox_v3,
    reset_code_sandbox_v3,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure each test gets a fresh singleton."""
    reset_code_sandbox_v3()
    yield
    reset_code_sandbox_v3()


# ═══════════════════════════════════════════════════════════════
# Test 1: Python execution
# ═══════════════════════════════════════════════════════════════

class TestPythonExecution:
    def test_python_hello(self):
        """Should successfully execute Python code and return output."""
        sand = CodeSandboxV3(use_docker=False)
        result = sand.run_python("print('hello v3')")
        assert "hello v3" in result.output
        assert result.exit_code == 0
        assert result.status == SandboxStatus.SUCCESS
        assert result.language == SandboxLanguage.PYTHON

    def test_python_multiline(self):
        """Should handle multi-line Python code."""
        sand = CodeSandboxV3(use_docker=False)
        code = "x = sum(range(100))\nprint(f'sum={x}')"
        result = sand.run_python(code)
        assert "sum=4950" in result.output
        assert result.exit_code == 0

    def test_python_error(self):
        """Should capture Python errors."""
        sand = CodeSandboxV3(use_docker=False)
        result = sand.run_python("1/0")
        assert result.exit_code != 0
        assert result.status == SandboxStatus.ERROR


# ═══════════════════════════════════════════════════════════════
# Test 2: Bash execution
# ═══════════════════════════════════════════════════════════════

class TestBashExecution:
    def test_bash_echo(self):
        """Should execute Bash commands."""
        sand = CodeSandboxV3(use_docker=False)
        result = sand.run_bash("echo 'bash works'")
        assert "bash works" in result.output
        assert result.exit_code == 0
        assert result.status == SandboxStatus.SUCCESS

    def test_bash_failure(self):
        """Should capture non-zero exit codes from Bash."""
        sand = CodeSandboxV3(use_docker=False)
        result = sand.run_bash("exit 42")
        assert result.exit_code == 42
        assert result.status == SandboxStatus.ERROR


# ═══════════════════════════════════════════════════════════════
# Test 3: JavaScript execution
# ═══════════════════════════════════════════════════════════════

class TestJavaScriptExecution:
    @pytest.fixture(autouse=True)
    def _require_node(self):
        import shutil
        if not shutil.which("node"):
            pytest.skip("Node.js not installed")

    def test_js_console_log(self):
        """Should execute JavaScript via Node.js."""
        sand = CodeSandboxV3(use_docker=False)
        result = sand.run_javascript("console.log('hello js')")
        assert "hello js" in result.output
        assert result.exit_code == 0
        assert result.language == SandboxLanguage.JAVASCRIPT

    def test_js_error(self):
        """Should capture JS errors."""
        sand = CodeSandboxV3(use_docker=False)
        result = sand.run_javascript("throw new Error('fail')")
        assert result.exit_code != 0 or "fail" in result.error


# ═══════════════════════════════════════════════════════════════
# Test 4: Go execution
# ═══════════════════════════════════════════════════════════════

class TestGoExecution:
    def test_go_hello(self):
        """Should execute Go code (skipped if Go not installed)."""
        import shutil
        if not shutil.which("go"):
            pytest.skip("Go compiler not installed")
        sand = CodeSandboxV3(use_docker=False)
        result = sand.run_go(
            'package main\nimport "fmt"\nfunc main() { fmt.Println("go works") }'
        )
        assert "go works" in result.output
        assert result.exit_code == 0
        assert result.language == SandboxLanguage.GO


# ═══════════════════════════════════════════════════════════════
# Test 5: Timeout enforcement
# ═══════════════════════════════════════════════════════════════

class TestTimeout:
    def test_python_timeout(self):
        """Should enforce timeout and return TIMEOUT status."""
        sand = CodeSandboxV3(timeout=1, use_docker=False)
        result = sand.run_python("import time; time.sleep(10)")
        assert result.status == SandboxStatus.TIMEOUT
        assert "TIMEOUT" in result.error

    def test_generic_run_timeout_override(self):
        """Should allow per-call timeout override."""
        sand = CodeSandboxV3(timeout=30, use_docker=False)
        result = sand.run("import time; time.sleep(5)", timeout=1)
        assert result.status == SandboxStatus.TIMEOUT


# ═══════════════════════════════════════════════════════════════
# Test 6: Security scan rejection
# ═══════════════════════════════════════════════════════════════

class TestSecurityScan:
    def test_python_critical_blocked(self):
        """Should reject code with critical patterns like rm -rf."""
        sand = CodeSandboxV3(enable_security_scan=True, use_docker=False)
        result = sand.run_python("import os; os.system('rm -rf /')")
        assert result.status == SandboxStatus.REJECTED
        assert "rejected" in result.error.lower()

    def test_python_safe_code_passes(self):
        """Safe code should pass the security scan."""
        sand = CodeSandboxV3(enable_security_scan=True, use_docker=False)
        result = sand.run_python("print(1+1)")
        assert result.status == SandboxStatus.SUCCESS

    def test_security_scan_disabled(self):
        """When security scan is disabled, dangerous code runs."""
        sand = CodeSandboxV3(enable_security_scan=False, use_docker=False)
        result = sand.run_python("import os; os.system('echo injected')")
        # Won't be rejected, will run (and likely succeed or fail depending on env)
        assert result.status != SandboxStatus.REJECTED

    def test_bash_critical_blocked(self):
        """Should block dangerous Bash commands."""
        sand = CodeSandboxV3(enable_security_scan=True, use_docker=False)
        result = sand.run("rm -rf /", language=SandboxLanguage.BASH)
        assert result.status == SandboxStatus.REJECTED


# ═══════════════════════════════════════════════════════════════
# Test 7: Audit logging
# ═══════════════════════════════════════════════════════════════

class TestAuditLogging:
    def test_audit_entry_created_on_run(self):
        """Each run should create an audit entry."""
        sand = CodeSandboxV3(use_docker=False)
        sand.run_python("print(42)")
        entries = sand.get_audit_entries()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.language == SandboxLanguage.PYTHON
        assert entry.code_hash
        assert len(entry.code_hash) == 64  # SHA256
        assert entry.status == SandboxStatus.SUCCESS

    def test_audit_export_to_file(self):
        """Should export audit log to a JSON file."""
        sand = CodeSandboxV3(use_docker=False)
        sand.run_python("print(1)")
        sand.run_bash("echo 2")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            exported = sand.export_audit_log(path)
            assert exported == path
            with open(path) as f:
                data = json.load(f)
            assert len(data) == 2
        finally:
            os.unlink(path)

    def test_audit_clear(self):
        """Should clear in-memory audit entries."""
        sand = CodeSandboxV3(use_docker=False)
        sand.run_python("print(1)")
        assert len(sand.get_audit_entries()) == 1
        sand.clear_audit_log()
        assert len(sand.get_audit_entries()) == 0

    def test_audit_risk_level_high(self):
        """High-risk code should be logged with appropriate risk level."""
        sand = CodeSandboxV3(use_docker=False, enable_security_scan=True)
        sand.run_python("import os; os.system('ls')")  # HIGH risk
        entries = sand.get_audit_entries()
        assert len(entries) == 1
        assert entries[0].risk_level == SandboxRiskLevel.HIGH


# ═══════════════════════════════════════════════════════════════
# Test 8: Result data model
# ═══════════════════════════════════════════════════════════════

class TestResultModel:
    def test_result_has_execution_id(self):
        """Result should include a unique execution ID."""
        sand = CodeSandboxV3(use_docker=False)
        r1 = sand.run_python("print(1)")
        r2 = sand.run_python("print(2)")
        assert r1.execution_id
        assert r2.execution_id
        assert r1.execution_id != r2.execution_id

    def test_result_to_dict(self):
        """Should serialize to dict correctly."""
        sand = CodeSandboxV3(use_docker=False)
        result = sand.run_python("print('test')")
        d = result.to_dict()
        assert d["output"] == result.output
        assert d["status"] == result.status.value
        assert d["execution_id"] == result.execution_id

    def test_result_truncation(self):
        """Output should be truncated when exceeding max_output."""
        sand = CodeSandboxV3(max_output=20, use_docker=False)
        result = sand.run_python("print('A' * 500)")
        assert result.truncated
        assert len(result.output) <= 20


# ═══════════════════════════════════════════════════════════════
# Test 9: Singleton pattern
# ═══════════════════════════════════════════════════════════════

class TestSingleton:
    def test_singleton_returns_same_instance(self):
        """get_code_sandbox_v3 should return the same object."""
        a = get_code_sandbox_v3()
        b = get_code_sandbox_v3()
        assert a is b

    def test_reset_creates_new_instance(self):
        """reset_code_sandbox_v3 should invalidate the singleton."""
        a = get_code_sandbox_v3()
        reset_code_sandbox_v3()
        b = get_code_sandbox_v3()
        assert a is not b


# ═══════════════════════════════════════════════════════════════
# Test 10: Runtime detection
# ═══════════════════════════════════════════════════════════════

class TestRuntimeDetection:
    def test_available_runtimes_includes_python_bash(self):
        """Python and Bash should always be listed as available."""
        sand = CodeSandboxV3(use_docker=False)
        runtimes = sand.available_runtimes()
        assert SandboxLanguage.PYTHON in runtimes
        assert SandboxLanguage.BASH in runtimes


# ═══════════════════════════════════════════════════════════════
# Test 11: Docker auto-detection (safely)
# ═══════════════════════════════════════════════════════════════

class TestDockerDetection:
    def test_docker_flag_false(self):
        """When use_docker=False, should not use Docker."""
        sand = CodeSandboxV3(use_docker=False)
        assert sand._docker_available is False

    def test_auto_detection_does_not_crash(self):
        """Auto-detection of Docker should never crash."""
        sand = CodeSandboxV3(use_docker=None)
        assert isinstance(sand._docker_available, bool)


# ═══════════════════════════════════════════════════════════════
# Test 12: Generic run() method
# ═══════════════════════════════════════════════════════════════

class TestGenericRun:
    def test_run_with_language_param(self):
        """The generic run() method should work with language parameter."""
        sand = CodeSandboxV3(use_docker=False)
        result = sand.run("print('generic')", language=SandboxLanguage.PYTHON)
        assert "generic" in result.output
        assert result.exit_code == 0

    def test_run_with_bash_language(self):
        """run() with Bash should work."""
        sand = CodeSandboxV3(use_docker=False)
        result = sand.run("echo 'generic bash'", language=SandboxLanguage.BASH)
        assert "generic bash" in result.output
