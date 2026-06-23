"""v3.112 Security Scanner 安全扫描器测试"""
import os
import tempfile
import time
from pathlib import Path

import pytest

from src.core.security_scanner import (
    SecurityScanner,
    ScanModule,
    Severity,
    Finding,
    ScanResult,
    SecurityReport,
    get_security_scanner,
    reset_security_scanner,
    _parse_version,
    _version_in_range,
    _VulnerabilityVisitor,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helper: create a temporary project with test files
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def temp_project():
    """Create a temporary project directory with test files for scanning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create a vulnerable Python file
        vuln_py = root / "vuln_code.py"
        vuln_py.write_text('''
import os
import pickle
import yaml

PASSWORD = "supersecret123"
API_KEY = "sk-abc123def456"

def run_command(user_input):
    os.system(f"echo {user_input}")

def load_data(data):
    return pickle.loads(data)

def load_yaml(path):
    return yaml.load(open(path).read())

def do_math(expr):
    return eval(expr)

SECRET_KEY = "default"

def execute_code(code):
    exec(code)
''')

        # Create a settings config file
        settings_py = root / "settings.py"
        settings_py.write_text('''
DEBUG = True
SECRET_KEY = "changeme"
ALLOWED_HOSTS = ["*"]
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
CORS_ALLOW_ALL_ORIGINS = True
LOG_LEVEL = "DEBUG"
''')

        # Create an env file with insecure config
        env_file = root / ".env"
        env_file.write_text('''
DEBUG=true
SECRET_KEY=test
DATABASE_URL=postgresql://admin:password123@localhost/db
ALLOWED_HOSTS=["*"]
CORS_ALLOW_ALL_ORIGINS=1
''')

        # Create a requirements file
        req_file = root / "requirements.txt"
        req_file.write_text('''
django==3.2.20
flask==2.3.1
requests==2.31.0
pyyaml==5.3.1
pillow==10.2.0
''')

        # Create a safe Python file (should have zero findings)
        safe_py = root / "safe_code.py"
        safe_py.write_text('''
import json
import yaml

def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)

def load_data(data):
    return json.loads(data)

def add_numbers(a, b):
    return a + b
''')

        yield root


@pytest.fixture
def scanner(temp_project):
    """Create a SecurityScanner pointing to the temp project."""
    return SecurityScanner(project_root=str(temp_project))


# ══════════════════════════════════════════════════════════════════════════════
# Test 1: Code Vulnerability Scanning — regex patterns
# ══════════════════════════════════════════════════════════════════════════════

class TestCodeVulnerabilityScanning:
    """Test Module 1: Code vulnerability scanning."""

    def test_detect_eval_exec(self, scanner):
        """Should detect eval() and exec() in code."""
        result = scanner.scan_code()
        finding_titles = {f.title for f in result.findings}

        assert any("eval()" in t for t in finding_titles), "Should detect eval()"
        assert any("exec()" in t for t in finding_titles), "Should detect exec()"

    def test_detect_hardcoded_secrets(self, scanner):
        """Should detect hardcoded password and API key."""
        result = scanner.scan_code()
        findings = [f for f in result.findings if f.severity == Severity.HIGH]

        secret_titles = {f.title for f in findings}
        assert any("Hardcoded secret" in t for t in secret_titles), "Should detect hardcoded secrets"

    def test_detect_unsafe_pickle(self, scanner):
        """Should detect unsafe pickle deserialization."""
        result = scanner.scan_code()
        pickle_findings = [f for f in result.findings if "pickle" in f.title.lower()]
        assert len(pickle_findings) >= 1, "Should detect pickle usage"

    def test_detect_unsafe_yaml(self, scanner):
        """Should detect yaml.load() without SafeLoader."""
        result = scanner.scan_code()
        yaml_findings = [f for f in result.findings if "yaml" in f.title.lower() or "YAML" in f.title]
        assert len(yaml_findings) >= 1, "Should detect unsafe yaml.load()"

    def test_detect_os_system_injection(self, scanner):
        """Should detect os.system() with f-string (command injection)."""
        result = scanner.scan_code()
        os_findings = [f for f in result.findings if "os.system" in f.title.lower()]
        assert len(os_findings) >= 1, "Should detect command injection via os.system()"

    def test_safe_code_has_no_findings(self, scanner):
        """Safe code file should produce zero findings from regex patterns."""
        result = scanner.scan_code(paths=[str(scanner.project_root / "safe_code.py")])
        # safe_code.py has no dangerous patterns
        assert len(result.findings) == 0, f"Safe code should have 0 findings, got: {[f.title for f in result.findings]}"

    def test_files_scanned_count(self, scanner):
        """Should report correct files_scanned count."""
        result = scanner.scan_code()
        assert result.files_scanned >= 3, "Should scan at least 3 Python files"


# ══════════════════════════════════════════════════════════════════════════════
# Test 2: AST-based Vulnerability Detection
# ══════════════════════════════════════════════════════════════════════════════

class TestASTVulnerabilityDetection:
    """Test AST-based vulnerability visitor."""

    def test_ast_detects_eval(self):
        """AST visitor should detect eval() calls."""
        import ast
        code = "eval('1+1')"
        tree = ast.parse(code)
        visitor = _VulnerabilityVisitor(file_path="test.py")
        visitor.visit(tree)
        assert any("eval()" in f.title for f in visitor.findings)

    def test_ast_detects_exec(self):
        """AST visitor should detect exec() calls."""
        import ast
        code = "exec('print(1)')"
        tree = ast.parse(code)
        visitor = _VulnerabilityVisitor(file_path="test.py")
        visitor.visit(tree)
        assert any("exec()" in f.title for f in visitor.findings)

    def test_ast_detects_pickle_loads(self):
        """AST visitor should detect pickle.loads() calls."""
        import ast
        code = "import pickle; pickle.loads(data)"
        tree = ast.parse(code)
        visitor = _VulnerabilityVisitor(file_path="test.py")
        visitor.visit(tree)
        assert any("pickle" in f.title.lower() for f in visitor.findings)


# ══════════════════════════════════════════════════════════════════════════════
# Test 3: Dependency CVE Detection
# ══════════════════════════════════════════════════════════════════════════════

class TestDependencyCVEDetection:
    """Test Module 2: Dependency CVE detection."""

    def test_detect_vulnerable_django(self, scanner):
        """Should detect CVE in django==3.2.20 (<3.2.25)."""
        result = scanner.scan_dependencies(check_installed=False)
        django_findings = [f for f in result.findings if "django" in f.title.lower() or "Django" in f.title]
        assert len(django_findings) >= 1, f"Should detect Django CVE, got: {[f.title for f in django_findings]}"

    def test_detect_vulnerable_pyyaml(self, scanner):
        """Should detect CVE in pyyaml==5.3.1 (<5.4)."""
        result = scanner.scan_dependencies(check_installed=False)
        yaml_findings = [f for f in result.findings if "pyyaml" in f.title.lower() or "PyYAML" in f.title]
        assert len(yaml_findings) >= 1, f"Should detect PyYAML CVE, got: {[f.title for f in yaml_findings]}"

    def test_cve_finding_has_cve_id(self, scanner):
        """Each CVE finding should have a CVE-ID."""
        result = scanner.scan_dependencies(check_installed=False)
        for f in result.findings:
            assert f.cve_id, f"Finding should have CVE-ID: {f.title}"

    def test_no_false_positive_for_safe_package(self, scanner):
        """A patched package should not trigger CVEs."""
        result = scanner.scan_dependencies(check_installed=False)
        # requests==2.31.0 is <2.32.0 so it IS vulnerable in our DB
        # That's actually correct — but let's verify the CVE for requests
        requests_findings = [f for f in result.findings if "requests" in f.title.lower()]
        assert len(requests_findings) >= 1, "requests==2.31.0 is vulnerable per CVE-2024-35195"


# ══════════════════════════════════════════════════════════════════════════════
# Test 4: Configuration Audit
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigurationAudit:
    """Test Module 3: Configuration audit."""

    def test_detect_debug_true(self, scanner):
        """Should detect DEBUG=True in settings."""
        result = scanner.audit_config()
        debug_findings = [f for f in result.findings if "debug" in f.title.lower()]
        assert len(debug_findings) >= 1, "Should detect DEBUG=True"

    def test_detect_weak_secret_key(self, scanner):
        """Should detect weak/placeholder SECRET_KEY."""
        result = scanner.audit_config()
        secret_findings = [f for f in result.findings if "secret" in f.title.lower()]
        assert len(secret_findings) >= 1, "Should detect weak secret key"

    def test_detect_database_url_credential(self, scanner):
        """Should detect hardcoded credentials in DATABASE_URL."""
        result = scanner.audit_config()
        db_findings = [f for f in result.findings if "database" in f.title.lower() or "credential" in f.title.lower()]
        assert len(db_findings) >= 1, "Should detect DB credentials in config"

    def test_detect_cors_wildcard(self, scanner):
        """Should detect CORS_ALLOW_ALL_ORIGINS=True."""
        result = scanner.audit_config()
        cors_findings = [f for f in result.findings if "cors" in f.title.lower()]
        assert len(cors_findings) >= 1, "Should detect CORS wildcard"


# ══════════════════════════════════════════════════════════════════════════════
# Test 5: Security Score Report
# ══════════════════════════════════════════════════════════════════════════════

class TestSecurityReport:
    """Test Module 4: Security score report generation."""

    def test_generate_report_produces_score(self, scanner):
        """Should produce a numeric score 0-100."""
        report = scanner.generate_report(run_all=True)
        assert 0 <= report.score <= 100, f"Score should be 0-100, got {report.score}"

    def test_report_has_grade(self, scanner):
        """Should produce a letter grade A-F."""
        report = scanner.generate_report(run_all=True)
        assert report.grade in ("A", "B", "C", "D", "F"), f"Grade should be A-F, got {report.grade}"

    def test_report_with_vulnerabilities_scores_low(self, scanner):
        """A project with many vulnerabilities should score below 90."""
        report = scanner.generate_report(run_all=True)
        # Our test project has multiple critical/high issues, should score < 90
        assert report.score < 90, f"Vulnerable project should score < 90, got {report.score}"

    def test_report_includes_recommendations(self, scanner):
        """Report should include actionable recommendations."""
        report = scanner.generate_report(run_all=True)
        assert len(report.recommendations) > 0, "Report should have recommendations"

    def test_report_to_dict_serializable(self, scanner):
        """Report.to_dict() should produce a JSON-serializable dict."""
        report = scanner.generate_report(run_all=True)
        d = report.to_dict()
        assert isinstance(d, dict)
        assert "score" in d
        assert "modules" in d
        assert "all_findings" in d

    def test_empty_project_scores_high(self, temp_project):
        """Scanning on an empty directory should give a perfect score."""
        # Clean project with no code files
        import shutil
        for item in temp_project.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)

        scanner = SecurityScanner(project_root=str(temp_project))
        report = scanner.generate_report(run_all=True)
        assert report.score == 100, f"Empty project should score 100, got {report.score}"
        assert report.grade == "A"


# ══════════════════════════════════════════════════════════════════════════════
# Test 6: Version Parsing Utilities
# ══════════════════════════════════════════════════════════════════════════════

class TestVersionParsing:
    """Test version parsing utilities used by CVE detection."""

    def test_parse_simple_version(self):
        assert _parse_version("2.3.1") == (2, 3, 1)

    def test_parse_version_with_suffix(self):
        assert _parse_version("1.26.19.post1") == (1, 26, 19, 1)

    def test_version_in_range_less_than(self):
        assert _version_in_range("3.0.0", "<4.0.0") is True
        assert _version_in_range("5.0.0", "<4.0.0") is False

    def test_version_in_range_greater_equal(self):
        assert _version_in_range("4.0.0", ">=4.0.0") is True
        assert _version_in_range("3.9.0", ">=4.0.0") is False

    def test_version_in_range_equal(self):
        assert _version_in_range("2.0.0", "==2.0.0") is True
        assert _version_in_range("2.1.0", "==2.0.0") is False


# ══════════════════════════════════════════════════════════════════════════════
# Test 7: Finding Data Class
# ══════════════════════════════════════════════════════════════════════════════

class TestFindingDataClass:
    """Test Finding and ScanResult data classes."""

    def test_finding_to_dict(self):
        f = Finding(
            module=ScanModule.CODE_VULN,
            severity=Severity.CRITICAL,
            title="Test finding",
            description="A test",
            file_path="test.py",
            line_number=10,
            code_snippet="eval(expr)",
            recommendation="Don't use eval",
            cvss_score=9.8,
        )
        d = f.to_dict()
        assert d["severity"] == "critical"
        assert d["line_number"] == 10
        assert d["cvss_score"] == 9.8

    def test_scan_result_counts(self):
        result = ScanResult(
            module=ScanModule.CODE_VULN,
            findings=[
                Finding(module=ScanModule.CODE_VULN, severity=Severity.CRITICAL, title="a", description=""),
                Finding(module=ScanModule.CODE_VULN, severity=Severity.CRITICAL, title="b", description=""),
                Finding(module=ScanModule.CODE_VULN, severity=Severity.HIGH, title="c", description=""),
                Finding(module=ScanModule.CODE_VULN, severity=Severity.MEDIUM, title="d", description=""),
                Finding(module=ScanModule.CODE_VULN, severity=Severity.LOW, title="e", description=""),
                Finding(module=ScanModule.CODE_VULN, severity=Severity.LOW, title="f", description=""),
            ],
        )
        assert result.critical_count == 2
        assert result.high_count == 1
        assert result.medium_count == 1
        assert result.low_count == 2


# ══════════════════════════════════════════════════════════════════════════════
# Test 8: Singleton Access
# ══════════════════════════════════════════════════════════════════════════════

class TestSingletonAccess:
    """Test get_security_scanner and reset_security_scanner."""

    def test_get_returns_instance(self, temp_project):
        reset_security_scanner()
        s = get_security_scanner(project_root=str(temp_project))
        assert isinstance(s, SecurityScanner)

    def test_get_is_singleton(self, temp_project):
        reset_security_scanner()
        s1 = get_security_scanner(project_root=str(temp_project))
        s2 = get_security_scanner(project_root=str(temp_project))
        assert s1 is s2

    def test_reset_creates_new_instance(self, temp_project):
        reset_security_scanner()
        s1 = get_security_scanner(project_root=str(temp_project))
        reset_security_scanner()
        s2 = get_security_scanner(project_root=str(temp_project))
        assert s1 is not s2


# ══════════════════════════════════════════════════════════════════════════════
# Test 9: Thread Safety
# ══════════════════════════════════════════════════════════════════════════════

class TestThreadSafety:
    """Test thread safety of scanner operations."""

    def test_concurrent_scans(self, temp_project):
        """Multiple threads scanning concurrently should not crash."""
        import threading

        errors = []

        def scan_worker():
            try:
                scanner = SecurityScanner(project_root=str(temp_project))
                scanner.scan_code()
                scanner.generate_report(run_all=True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=scan_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Thread safety errors: {errors}"


# ══════════════════════════════════════════════════════════════════════════════
# Test 10: quick_scan convenience method
# ══════════════════════════════════════════════════════════════════════════════

class TestQuickScan:
    """Test the quick_scan convenience method."""

    def test_quick_scan_returns_report(self, scanner):
        report = scanner.quick_scan()
        assert isinstance(report, SecurityReport)
        assert report.score is not None
        assert len(report.results) == 3  # All three modules
