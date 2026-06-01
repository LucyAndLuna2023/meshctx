"""
P0-4 代码审查测试 — 对标 Goose review
=====================================
测试 CodeReviewer 的各项功能:
  - review_file() 静态分析
  - project_review() 目录级审查
  - ai_deep_review() LLM 深度审查
  - review_summary() 评分汇总
  - ReviewIssue 数据类
  - CLI review 命令
"""
import os
import sys
import tempfile
import importlib.util
from pathlib import Path

import pytest

# 直接加载模块，避免链式 import 触发缺失依赖 (如 pydantic)
_MODULE_PATH = os.path.join(os.path.dirname(__file__), "..", "src", "core", "code_reviewer.py")
_spec = importlib.util.spec_from_file_location("code_reviewer", _MODULE_PATH)
_code_reviewer_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_code_reviewer_mod)

CodeReviewer = _code_reviewer_mod.CodeReviewer
ReviewIssue = _code_reviewer_mod.ReviewIssue
SEVERITY_ORDER = _code_reviewer_mod.SEVERITY_ORDER
PYTHON_PATTERNS = _code_reviewer_mod.PYTHON_PATTERNS
JAVASCRIPT_PATTERNS = _code_reviewer_mod.JAVASCRIPT_PATTERNS
GENERAL_PATTERNS = _code_reviewer_mod.GENERAL_PATTERNS


# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def reviewer():
    """创建 CodeReviewer 实例。"""
    return CodeReviewer()


@pytest.fixture
def temp_project():
    """创建临时项目目录，包含多种测试文件。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Python 测试文件 — 包含多种安全问题
        vuln_py = root / "vuln_code.py"
        vuln_py.write_text('''"""有安全问题的 Python 代码"""
import os
import pickle
import hashlib

API_KEY = "sk-abc123def456ghi789"
PASSWORD = "supersecret"
SECRET_KEY = "my-secret-token-123"

def run_cmd(user_input):
    """命令注入漏洞"""
    os.system(f"echo {user_input}")

def unsafe_pickle(data):
    """不安全反序列化"""
    return pickle.loads(data)

def bad_sql(cursor, uid):
    """SQL 注入风险"""
    cursor.execute(f"SELECT * FROM users WHERE id = {uid}")

def bare_except():
    try:
        risky_operation()
    except:
        pass

def weak_hash(password):
    return hashlib.md5(password.encode()).hexdigest()
''')

        # JavaScript 测试文件 — 包含 XSS 和原型污染
        vuln_js = root / "vuln_script.js"
        vuln_js.write_text('''// 有安全问题的 JavaScript 代码
function unsafeDisplay(userData) {
    document.getElementById("output").innerHTML = userData;
}

function unsafeExec(code) {
    eval(code);
}

function protoPollute(obj, key, value) {
    obj.__proto__[key] = value;
}

function storeToken(token) {
    localStorage.setItem("token", token);
}

// TODO: refactor this
function longFunc() {
    console.log("debug");
}
''')

        # 干净的 Python 文件（应无问题或极少问题）
        clean_py = root / "clean_code.py"
        clean_py.write_text('''"""干净的 Python 代码"""
import logging

logger = logging.getLogger(__name__)

def fetch_user(db, user_id: int) -> dict:
    """使用参数化查询获取用户。"""
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    return cursor.fetchone()

def validate_input(value: str) -> str:
    """输入校验。"""
    return value.strip()[:100]
''')

        yield root


# ══════════════════════════════════════════════════════════════════════════════
# 测试 1: ReviewIssue 数据类
# ══════════════════════════════════════════════════════════════════════════════

class TestReviewIssue:
    """ReviewIssue 数据类单元测试。"""

    def test_creation_defaults(self):
        """测试默认值创建。"""
        issue = ReviewIssue(file="test.py")
        assert issue.file == "test.py"
        assert issue.line == 0
        assert issue.severity == "info"
        assert issue.category == "style"
        assert issue.title == ""
        assert issue.description == ""
        assert issue.suggestion == ""

    def test_creation_full(self):
        """测试完整参数创建。"""
        issue = ReviewIssue(
            file="app.py", line=42,
            severity="critical", category="security",
            title="XSS风险", description="存在XSS漏洞",
            suggestion="使用textContent"
        )
        assert issue.file == "app.py"
        assert issue.line == 42
        assert issue.severity == "critical"
        assert issue.category == "security"
        assert issue.severity_order == 0

    def test_to_dict(self):
        """测试 to_dict() 序列化。"""
        issue = ReviewIssue(
            file="app.py", line=10,
            severity="high", category="bug",
            title="Bug!", description="有问题"
        )
        d = issue.to_dict()
        assert isinstance(d, dict)
        assert d["file"] == "app.py"
        assert d["line"] == 10
        assert d["severity"] == "high"
        assert d["category"] == "bug"
        assert d["title"] == "Bug!"

    def test_severity_order(self):
        """测试严重度排序权重。"""
        assert ReviewIssue(file="", severity="critical").severity_order == 0
        assert ReviewIssue(file="", severity="high").severity_order == 1
        assert ReviewIssue(file="", severity="medium").severity_order == 2
        assert ReviewIssue(file="", severity="low").severity_order == 3
        assert ReviewIssue(file="", severity="info").severity_order == 4


# ══════════════════════════════════════════════════════════════════════════════
# 测试 2: review_file() 静态分析 — Python
# ══════════════════════════════════════════════════════════════════════════════

class TestReviewFilePython:
    """Python 文件静态分析测试。"""

    def test_detect_eval(self, reviewer):
        """检测 eval() 调用。"""
        issues = reviewer.review_file("test.py", "x = eval(input())", "python")
        titles = [i.title for i in issues]
        assert any("eval" in t.lower() for t in titles)

    def test_detect_hardcoded_api_key(self, reviewer):
        """检测硬编码 API Key。"""
        issues = reviewer.review_file("test.py", 'API_KEY = "sk-abc123xyz"', "python")
        titles = [i.title for i in issues]
        assert any("API Key" in t or "apikey" in t.lower() for t in titles)

    def test_detect_hardcoded_password(self, reviewer):
        """检测硬编码密码。"""
        issues = reviewer.review_file("test.py", 'PASSWORD = "secret123"', "python")
        titles = [i.title for i in issues]
        assert any("密码" in t or "password" in t.lower() for t in titles)

    def test_detect_sql_injection(self, reviewer):
        """检测 SQL 注入风险（f-string）。"""
        issues = reviewer.review_file("test.py",
            'cursor.execute(f"SELECT * FROM t WHERE id = {uid}")', "python")
        titles = [i.title for i in issues]
        assert any("注入" in t for t in titles)

    def test_detect_bare_except(self, reviewer):
        """检测裸 except 子句。"""
        content = '''try:
    risky()
except:
    pass'''
        issues = reviewer.review_file("test.py", content, "python")
        titles = [i.title for i in issues]
        assert any("bare" in t.lower() or "裸" in t for t in titles)

    def test_detect_pickle(self, reviewer):
        """检测 pickle 反序列化。"""
        issues = reviewer.review_file("test.py", "x = pickle.loads(data)", "python")
        titles = [i.title for i in issues]
        assert any("pickle" in t.lower() for t in titles)

    def test_detect_os_system(self, reviewer):
        """检测 os.system() 调用。"""
        issues = reviewer.review_file("test.py", "os.system('ls')", "python")
        titles = [i.title for i in issues]
        assert any("os.system" in t.lower() for t in titles)

    def test_detect_shell_true(self, reviewer):
        """检测 subprocess shell=True。"""
        issues = reviewer.review_file("test.py",
            'subprocess.call("ls", shell=True)', "python")
        titles = [i.title for i in issues]
        assert any("shell" in t.lower() or "shell=true" in t.lower() for t in titles)

    def test_detect_md5(self, reviewer):
        """检测 MD5 用于安全场景。"""
        issues = reviewer.review_file("test.py",
            "h = hashlib.md5(b'password')", "python")
        titles = [i.title for i in issues]
        assert any("md5" in t.lower() for t in titles)

    def test_clean_code_few_issues(self, reviewer):
        """干净代码应产生较少问题。"""
        clean = '''"""干净的 Python 代码"""\nimport logging\nlogger = logging.getLogger(__name__)\n\ndef fetch_user(db, uid):\n    c = db.cursor()\n    c.execute("SELECT * FROM users WHERE id = ?", (uid,))\n    return c.fetchone()\n'''
        issues = reviewer.review_file("clean.py", clean, "python")
        # 干净代码不应有 critical/high 问题
        critical_high = [i for i in issues if i.severity in ("critical", "high")]
        assert len(critical_high) == 0, f"干净代码不应有高危问题: {critical_high}"

    def test_long_function_detection(self, reviewer):
        """检测过长函数。"""
        # 生成 110 行函数体
        lines = ["def my_long_func():"] + ["    x = 1"] * 110
        content = "\n".join(lines)
        issues = reviewer.review_file("long.py", content, "python")
        titles = [i.title for i in issues]
        assert any("函数过长" in t or "too long" in t.lower() for t in titles)

    def test_mutable_default_args(self, reviewer):
        """检测可变默认参数。"""
        issues = reviewer.review_file("test.py",
            "def f(items=[]):\n    pass", "python")
        titles = [i.title for i in issues]
        assert any("可变默认" in t or "mutable" in t.lower() for t in titles)


# ══════════════════════════════════════════════════════════════════════════════
# 测试 3: review_file() 静态分析 — JavaScript
# ══════════════════════════════════════════════════════════════════════════════

class TestReviewFileJavaScript:
    """JavaScript 文件静态分析测试。"""

    def test_detect_innerhtml(self, reviewer):
        """检测 innerHTML XSS。"""
        issues = reviewer.review_file("app.js",
            'document.getElementById("x").innerHTML = userData;', "javascript")
        titles = [i.title for i in issues]
        assert any("innerhtml" in t.lower() for t in titles)

    def test_detect_eval_js(self, reviewer):
        """检测 JavaScript eval()。"""
        issues = reviewer.review_file("app.js", "eval(userInput)", "javascript")
        titles = [i.title for i in issues]
        assert any("eval" in t.lower() for t in titles)

    def test_detect_proto_pollution(self, reviewer):
        """检测原型污染（__proto__）。"""
        issues = reviewer.review_file("app.js",
            "obj.__proto__[key] = val;", "javascript")
        titles = [i.title for i in issues]
        assert any("原型" in t or "proto" in t.lower() for t in titles)

    def test_detect_localstorage_token(self, reviewer):
        """检测 localStorage 存储 Token。"""
        issues = reviewer.review_file("app.js",
            'localStorage.setItem("token", jwt);', "javascript")
        titles = [i.title for i in issues]
        assert any("localstorage" in t.lower() for t in titles)

    def test_detect_document_write(self, reviewer):
        """检测 document.write() 调用。"""
        issues = reviewer.review_file("app.js",
            'document.write("<div>" + userHtml + "</div>");', "javascript")
        titles = [i.title for i in issues]
        assert any("document.write" in t.lower() for t in titles)

    def test_detect_new_function(self, reviewer):
        """检测 new Function() 动态代码。"""
        issues = reviewer.review_file("app.js",
            'var fn = new Function("return " + expr);', "javascript")
        titles = [i.title for i in issues]
        assert any("new Function" in t.lower() or "new function" in t.lower() for t in titles)


# ══════════════════════════════════════════════════════════════════════════════
# 测试 4: review_summary() 评分汇总
# ══════════════════════════════════════════════════════════════════════════════

class TestReviewSummary:
    """review_summary() 评分测试。"""

    def test_empty_issues(self, reviewer):
        """无问题时满分。"""
        summary = reviewer.review_summary([])
        assert summary["total_issues"] == 0
        assert summary["score"] == 100
        assert summary["verdict"] == "✅ Ready"

    def test_critical_drains_score(self, reviewer):
        """critical 问题大幅扣分。"""
        issues = [
            ReviewIssue(file="a.py", severity="critical", category="security",
                       title="eval()"),
        ]
        summary = reviewer.review_summary(issues)
        assert summary["score"] == 85  # 100 - 15
        assert summary["by_severity"]["critical"] == 1

    def test_mixed_severities(self, reviewer):
        """混合严重度统计正确。"""
        issues = [
            ReviewIssue(file="a.py", severity="critical", category="security",
                       title="eval"),
            ReviewIssue(file="b.py", severity="high", category="bug",
                       title="bare except"),
            ReviewIssue(file="c.py", severity="medium", category="style",
                       title="import *"),
            ReviewIssue(file="d.py", severity="low", category="style",
                       title="print"),
            ReviewIssue(file="e.py", severity="info", category="docs",
                       title="TODO"),
        ]
        summary = reviewer.review_summary(issues)
        assert summary["total_issues"] == 5
        assert summary["score"] == 100 - 15 - 8 - 3 - 1  # = 73
        assert summary["by_severity"]["critical"] == 1
        assert summary["by_severity"]["high"] == 1
        assert summary["by_severity"]["medium"] == 1
        assert summary["by_severity"]["low"] == 1
        assert summary["by_severity"]["info"] == 1
        assert summary["by_category"]["security"] == 1
        assert summary["by_category"]["bug"] == 1
        assert summary["by_category"]["style"] == 2
        assert summary["by_category"]["docs"] == 1

    def test_verdict_thresholds(self, reviewer):
        """评判阈值: >=80 Ready, >=60 Review, <60 Needs Work。"""
        # Ready
        assert reviewer.review_summary([])["verdict"] == "✅ Ready"
        # Review
        issues = [ReviewIssue(file="x", severity="high", category="bug", title="x")
                  for _ in range(5)]
        assert reviewer.review_summary(issues)["verdict"] == "⚠ Review"
        # Needs Work
        issues = [ReviewIssue(file="x", severity="critical", category="security",
                             title="x") for _ in range(5)]
        assert reviewer.review_summary(issues)["verdict"] == "❌ Needs Work"


# ══════════════════════════════════════════════════════════════════════════════
# 测试 5: project_review() 项目级审查
# ══════════════════════════════════════════════════════════════════════════════

class TestProjectReview:
    """project_review() 目录审查测试。"""

    def test_scans_directory(self, reviewer, temp_project):
        """扫描目录并找到所有支持的文件。"""
        result = reviewer.project_review(str(temp_project))
        assert result["files_scanned"] >= 2  # vuln_code.py + vuln_script.js
        assert result["total_issues"] > 0
        assert "score" in result
        assert "verdict" in result

    def test_issues_sorted_by_severity(self, reviewer, temp_project):
        """返回结果中 issues 按严重度排序。"""
        result = reviewer.project_review(str(temp_project))
        issues = result["issues"]
        if len(issues) >= 2:
            sevs = [i["severity"] for i in issues]
            # 验证严重度排序: critical 应在 high/medium/low/info 之前
            for i in range(len(sevs) - 1):
                assert SEVERITY_ORDER.get(sevs[i], 99) <= SEVERITY_ORDER.get(sevs[i+1], 99), \
                    f"顺序错误: {sevs[i]} > {sevs[i+1]}"

    def test_by_file_stats(self, reviewer, temp_project):
        """by_file 统计文件级问题分布。"""
        result = reviewer.project_review(str(temp_project))
        assert "by_file" in result
        assert len(result["by_file"]) >= 1

    def test_excludes_dirs(self, reviewer, temp_project):
        """排除目录（如 __pycache__）被正确跳过。"""
        # 创建模拟的排除目录
        exclude_dir = Path(temp_project) / "__pycache__"
        exclude_dir.mkdir(exist_ok=True)
        (exclude_dir / "cached.py").write_text("eval(x)")

        result = reviewer.project_review(str(temp_project),
                                         exclude_dirs={"__pycache__"})
        # __pycache__ 下的文件不应出现在结果中
        for issue in result["issues"]:
            assert "__pycache__" not in issue["file"], \
                f"排除目录不应被扫描: {issue['file']}"

    def test_handles_nonexistent_directory(self, reviewer):
        """不存在目录应正常处理。"""
        result = reviewer.project_review("/nonexistent/path/xyz123/")
        assert result["files_scanned"] == 0
        assert result["total_issues"] == 0
        assert result["score"] == 100


# ══════════════════════════════════════════════════════════════════════════════
# 测试 6: ai_deep_review() LLM 深度审查
# ══════════════════════════════════════════════════════════════════════════════

class TestAIDeepReview:
    """ai_deep_review() 深度审查测试。"""

    def test_returns_none_without_llm(self, reviewer):
        """无 LLM 配置时返回 None（优雅降级）。"""
        result = reviewer.ai_deep_review("print(1)", language="python")
        # 无模型配置时应返回 None，不抛异常
        assert result is None

    def test_handles_empty_content(self, reviewer):
        """空内容不崩溃。"""
        result = reviewer.ai_deep_review("", language="python")
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# 测试 7: 模式覆盖完整性
# ══════════════════════════════════════════════════════════════════════════════

class TestPatternCoverage:
    """模式库完整性测试。"""

    def test_python_patterns_not_empty(self):
        """Python 模式库非空。"""
        assert len(PYTHON_PATTERNS) >= 10, f"Python 模式应有充分覆盖，当前 {len(PYTHON_PATTERNS)}"

    def test_javascript_patterns_not_empty(self):
        """JavaScript 模式库非空。"""
        assert len(JAVASCRIPT_PATTERNS) >= 5, f"JavaScript 模式应有充分覆盖，当前 {len(JAVASCRIPT_PATTERNS)}"

    def test_general_patterns_not_empty(self):
        """通用模式库非空。"""
        assert len(GENERAL_PATTERNS) >= 2

    def test_all_patterns_are_tuples(self):
        """所有模式条目格式正确 (5元组)。"""
        all_pats = PYTHON_PATTERNS + JAVASCRIPT_PATTERNS + GENERAL_PATTERNS
        for pat in all_pats:
            assert len(pat) == 5, f"模式应为5元组: {pat}"
            assert hasattr(pat[0], 'search'), f"第一个元素应为正则对象: {pat}"

    def test_severity_order_complete(self):
        """严重度排序表覆盖所有已知严重度。"""
        for sev in ("critical", "high", "medium", "low", "info"):
            assert sev in SEVERITY_ORDER


# ══════════════════════════════════════════════════════════════════════════════
# 测试 8: 边界条件
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """边界条件测试。"""

    def test_empty_file(self, reviewer):
        """空文件审查。"""
        issues = reviewer.review_file("empty.py", "", "python")
        assert isinstance(issues, list)

    def test_binary_content_survives(self, reviewer):
        """二进制内容不崩溃（errors='replace' 处理）。"""
        issues = reviewer.review_file("bin.py", "\x00\xff\xfe" * 100, "python")
        assert isinstance(issues, list)

    def test_unknown_language_falls_back(self, reviewer):
        """未知语言回退到 Python 模式。"""
        issues = reviewer.review_file("test.xyz", "eval(x)", "ruby")
        assert isinstance(issues, list)

    def test_no_duplicate_issues_same_line(self, reviewer):
        """同一行不应重复报告同一模式。"""
        # 使用 exec()，它同时匹配 exec 模式和通用 exec 模式
        issues = reviewer.review_file("test.py", "exec(code)", "python")
        titles = [i.title for i in issues]
        # exec 模式应精确匹配一次
        assert titles.count("exec() 调用检测") <= 1
