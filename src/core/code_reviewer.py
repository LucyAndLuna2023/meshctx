"""
MeshCtx Code Review Plugin — AI-Powered PR Reviewer (对标Goose Review)
====================================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

增强版代码审查引擎，对标 Goose review 命令。
功能:
  - 静态分析 PATTERNS 覆盖 Python/JavaScript/通用安全问题
  - project_review() 目录级批量审查，按严重度排序汇总
  - ai_deep_review() LLM 深度审查（可选，优雅降级）
  - review_summary() 评分与统计

纯中文注释

License: AGPLv3 for non-commercial use only.
"""
import re
import os
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# 严重度排序权重，用于 project_review 汇总排序
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass
class ReviewIssue:
    """审查发现的单个问题。"""
    file: str
    line: int = 0
    severity: str = "info"  # critical, high, medium, low, info
    category: str = "style"  # bug, security, style, performance, docs
    title: str = ""
    description: str = ""
    suggestion: str = ""

    def to_dict(self) -> Dict:
        return {
            "file": self.file, "line": self.line,
            "severity": self.severity, "category": self.category,
            "title": self.title, "description": self.description,
            "suggestion": self.suggestion,
        }

    @property
    def severity_order(self) -> int:
        """返回严重度排序序号，用于排序。"""
        return SEVERITY_ORDER.get(self.severity, 99)


# ══════════════════════════════════════════════════════════════════════════════
# 静态分析模式库 — 对标 Goose review 的内置规则
# ══════════════════════════════════════════════════════════════════════════════

# Python 模式：覆盖安全、Bug、风格、性能
PYTHON_PATTERNS = [
    # ── 安全: 代码注入 ──
    (re.compile(r"\beval\s*\("), "critical", "security",
     "eval() 调用检测", "eval() 可执行任意代码，极具危险。使用 ast.literal_eval() 或完全避免。"),
    (re.compile(r"\bexec\s*\("), "critical", "security",
     "exec() 调用检测", "exec() 可执行任意代码。除非绝对必要，否则避免使用。"),
    (re.compile(r"\bcompile\s*\(.*,\s*['\"]exec['\"]"), "critical", "security",
     "compile() 动态执行", "compile() 配合 'exec' 模式可动态执行代码，审查输入来源。"),
    # ── 安全: 命令/Shell 注入 ──
    (re.compile(r"\bos\.system\s*\("), "high", "security",
     "os.system() 调用", "os.system() 易受命令注入攻击。使用 subprocess.run() 配合列表参数。"),
    (re.compile(r"\bos\.popen\s*\("), "high", "security",
     "os.popen() 调用", "os.popen() 易受注入攻击。使用 subprocess 模块替代。"),
    (re.compile(r"\bsubprocess\.(call|Popen|run)\s*\([^)]*shell\s*=\s*True"), "high", "security",
     "Shell=True 子进程调用", "shell=True 易受注入攻击。使用列表参数并避免 shell 解释。"),
    (re.compile(r"\bsubprocess\.(call|Popen|run)\s*\(\s*['\"][^'\"]*\$"), "high", "security",
     "子进程调用中拼接变量", "子进程命令中拼接用户输入可能导致命令注入。使用列表参数。"),
    # ── 安全: SQL 注入风险 ──
    (re.compile(r"\.execute\s*\(\s*['\"].*%(s|d|r|x)"), "critical", "security",
     "SQL 注入风险: % 格式化", "cursor.execute() 中使用 % 格式化存在 SQL 注入风险。使用参数化查询。"),
    (re.compile(r"\.execute\s*\(\s*(f['\"]|['\"].*\{)"), "critical", "security",
     "SQL 注入风险: f-string/拼接", "cursor.execute() 中使用 f-string 或字符串拼接存在 SQL 注入风险。"),
    (re.compile(r"\.execute\s*\(\s*['\"].*\s*\+\s*"), "high", "security",
     "SQL 语句字符串拼接", "execute() 中拼接 SQL 字符串存在注入风险。使用 ? 或 %s 占位符。"),
    # ── 安全: 硬编码凭证/Token ──
    (re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"][^'\"]{3,}['\"]"), "critical", "security",
     "硬编码密码", "切勿硬编码密码。使用环境变量或密钥管理服务。"),
    (re.compile(r"(?i)(api_key|apikey|api_secret)\s*[:=]\s*['\"][^'\"]{3,}['\"]"), "critical", "security",
     "硬编码 API Key", "使用环境变量或配置文件管理 API 密钥。"),
    (re.compile(r"(?i)(secret_key|secret_token|access_key)\s*[:=]\s*['\"][^'\"]{3,}['\"]"), "critical", "security",
     "硬编码 Secret/Token", "敏感凭证应存储在环境变量中，不可硬编码。"),
    (re.compile(r"(?i)(bearer\s+['\"][A-Za-z0-9\-_\.]{20,})"), "critical", "security",
     "硬编码 Bearer Token", "Bearer Token 不应硬编码在源码中。"),
    (re.compile(r"(?i)(jwt|auth_token|refresh_token)\s*[:=]\s*['\"][^'\"]{6,}['\"]"), "critical", "security",
     "硬编码 JWT/Auth Token", "认证 Token 应通过环境变量或安全存储注入。"),
    (re.compile(r"(?i)(private_key|private\s+key)\s*[:=]\s*['\"]-----BEGIN"), "critical", "security",
     "硬编码私钥", "私钥不应出现在源码中。使用文件引用或密钥管理服务。"),
    # ── 安全: 反序列化漏洞 ──
    (re.compile(r"\bpickle\.(loads|load)\s*\("), "high", "security",
     "pickle 反序列化", "pickle 反序列化可执行任意代码。使用 json 或更安全的序列化方式。"),
    (re.compile(r"\byaml\.load\s*\([^)]*(?!.*Loader\s*=)"), "medium", "security",
     "yaml.load() 不安全", "PyYAML 的 yaml.load() 默认不安全。使用 yaml.safe_load()。"),
    # ── 安全: 文件路径遍历 ──
    (re.compile(r"open\s*\(\s*['\"].*\.\./"), "high", "security",
     "路径遍历风险: ../", "open() 中使用相对路径遍历可能导致任意文件读取。使用 os.path.abspath() 校验。"),
    (re.compile(r"open\s*\(\s*['\"].*\.\.\\\\"), "high", "security",
     "路径遍历风险: ..\\", "Windows 路径遍历。使用 pathlib 或 os.path.realpath() 规范化。"),
    # ── 安全: 弱加密 ──
    (re.compile(r"\bhashlib\.md5\s*\("), "medium", "security",
     "MD5 哈希用于安全场景", "MD5 已被破解，不适合安全用途。使用 SHA-256 或 bcrypt。"),
    (re.compile(r"\bhashlib\.sha1\s*\("), "medium", "security",
     "SHA1 哈希用于安全场景", "SHA1 存在碰撞攻击风险。使用 SHA-256+ 系列。"),
    (re.compile(r"\bcrypt\.(hashpw|gensalt)\s*\("), "info", "security",
     "bcrypt 使用检测", "bcrypt 是安全的密码哈希方案 ✓。确认 rounds 参数充足。"),
    # ── Bug: 异常处理 ──
    (re.compile(r"^\s*except\s*:"), "high", "bug",
     "裸 except 子句", "捕获所有异常会隐藏 Bug。请指定具体异常类型。"),
    (re.compile(r"except\s+(Exception|BaseException)\s*:"), "medium", "bug",
     "捕获过于宽泛的异常", "捕获 Exception/BaseException 过于宽泛。请指定具体异常类型。"),
    (re.compile(r"except\s+\w+\s*:\s*\bpass\b"), "high", "bug",
     "空 except 块 (pass)", "忽略异常可能掩盖严重错误。至少记录日志。"),
    # ── Bug: 常见陷阱 ──
    (re.compile(r"\bassert\s+.+?=="), "low", "bug",
     "assert 用于业务逻辑", "assert 在 python -O 模式下被跳过。不要用 assert 做输入校验。"),
    (re.compile(r"\bfor\s+\w+\s+in\s+\w+[^:]*:\s*$"), "info", "style",
     "可变对象作为默认参数", "检查函数签名中是否使用了可变默认参数 (list/dict)。"),
    # ── 风格 ──
    (re.compile(r"\bimport\s+\*"), "medium", "style",
     "通配符导入 (import *)", "避免 'from x import *'。仅导入所需内容。"),
    (re.compile(r"\bprint\s*\(.*\)"), "low", "style",
     "print() 调试语句", "生产代码应使用 logging 替代 print()。"),
    (re.compile(r"(?i)TODO|FIXME|HACK|XXX"), "info", "docs",
     "TODO/FIXME 注释", "合并前处理 TODO/FIXME 注释。"),
    (re.compile(r"^\s*#\s*(TODO|FIXME|HACK)\b"), "info", "docs",
     "待办标记", "标注了待处理事项，合并前请确认。"),
    # ── 性能 ──
    (re.compile(r"\btime\.sleep\s*\(\s*\d+"), "medium", "performance",
     "time.sleep() 调用", "sleep 可能暗示竞态条件。使用适当的同步原语。"),
    (re.compile(r"\bfor\s+\w+\s+in\s+range\s*\(\s*len\s*\("), "low", "performance",
     "range(len(...)) 反模式", "使用 enumerate() 替代 range(len(...))。"),
    (re.compile(r"\+\s*=\s*['\"]\s*\+\s*['\"]"), "low", "performance",
     "循环中字符串拼接", "循环中字符串拼接低效。使用 ''.join() 或列表推导。"),
    # ── Flask/Django 特定 ──
    (re.compile(r"\bapp\.run\s*\(\s*debug\s*=\s*True"), "high", "security",
     "Flask debug=True", "生产环境切勿启用 Flask debug 模式。这会暴露代码和执行环境。"),
    (re.compile(r"\bDEBUG\s*=\s*True"), "medium", "security",
     "Django DEBUG=True", "生产环境切勿启用 Django DEBUG 模式。"),
    (re.compile(r"render_template_string\s*\("), "high", "security",
     "render_template_string() SSTI 风险", "可能存在服务端模板注入 (SSTI)。审查用户输入是否进入模板。"),
]

# JavaScript/TypeScript 模式
JAVASCRIPT_PATTERNS = [
    # ── XSS 风险 ──
    (re.compile(r"\beval\s*\("), "critical", "security",
     "eval() 调用", "eval() 极具危险，可导致代码注入和 XSS。"),
    (re.compile(r"\binnerHTML\s*="), "high", "security",
     "innerHTML 直接赋值", "innerHTML 可能导致 XSS。使用 textContent 或安全 DOM API。"),
    (re.compile(r"\bouterHTML\s*="), "high", "security",
     "outerHTML 直接赋值", "outerHTML 可能导致 XSS。使用安全 DOM 操作。"),
    (re.compile(r"\bdocument\.write\s*\("), "high", "security",
     "document.write() 调用", "document.write() 可能导致 XSS 和 DOM 破坏。避免使用。"),
    (re.compile(r"\binsertAdjacentHTML\s*\("), "medium", "security",
     "insertAdjacentHTML() 使用", "若参数来自用户输入，可能导致 XSS。请审查输入来源。"),
    (re.compile(r"\bdangerouslySetInnerHTML"), "high", "security",
     "React dangerouslySetInnerHTML", "确保 HTML 内容已经过消毒处理 (DOMPurify)。"),
    (re.compile(r"\bbypassSecurityTrust(?:Html|Script|Style|Url)\s*\("), "critical", "security",
     "Angular bypassSecurity 绕过", "绕过 Angular 安全机制极具风险，可能引入 XSS。"),
    # ── 原型污染 ──
    (re.compile(r"\b__proto__\s*\["), "critical", "security",
     "原型污染风险: __proto__", "通过 __proto__ 修改可能导致原型污染攻击。使用 Object.create(null)。"),
    (re.compile(r"\bconstructor\s*\[.*?\]\s*="), "high", "security",
     "原型污染风险: constructor", "constructor 属性修改可能导致原型污染。"),
    (re.compile(r"\bObject\.assign\s*\(.*?__proto__"), "high", "security",
     "Object.assign 污染风险", "Object.assign 配合用户数据可能导致原型污染。"),
    (re.compile(r"\bmerge\s*\(.*?(?:req\.body|req\.query|user)"), "medium", "security",
     "深层合并用户输入", "lodash.merge 等深层合并可能引入原型污染。使用安全合并函数。"),
    # ── 敏感数据 ──
    (re.compile(r"\blocalStorage\.setItem\s*\(\s*['\"](?:token|password|secret)"), "high", "security",
     "localStorage 存储敏感数据", "localStorage 可被 XSS 读取。敏感 Token 应使用 httpOnly cookie。"),
    (re.compile(r"\bsessionStorage\.setItem\s*\(\s*['\"](?:token|password)"), "medium", "security",
     "sessionStorage 存储敏感数据", "避免在 Web Storage 中存储敏感凭证。"),
    # ── 风格 ──
    (re.compile(r"\bconsole\.log\s*\("), "low", "style",
     "console.log() 调试语句", "生产构建前移除调试日志。"),
    (re.compile(r"\bconsole\.dir\s*\("), "low", "style",
     "console.dir() 调试语句", "生产构建前移除调试输出。"),
    (re.compile(r"(?i)TODO|FIXME|HACK"), "info", "docs",
     "TODO/FIXME 注释", "合并前处理 TODO/FIXME 注释。"),
    # ── 安全: 动态代码执行 ──
    (re.compile(r"\bnew\s+Function\s*\("), "critical", "security",
     "new Function() 动态代码", "类似于 eval()，可执行任意代码。避免使用。"),
    (re.compile(r"\bsetTimeout\s*\(\s*['\"][^'\"]*\$"), "high", "security",
     "setTimeout 字符串参数", "字符串形式的 setTimeout 会调用 eval()。使用函数引用。"),
    (re.compile(r"\bsetInterval\s*\(\s*['\"][^'\"]*\$"), "high", "security",
     "setInterval 字符串参数", "字符串形式的 setInterval 会调用 eval()。使用函数引用。"),
]

# 通用模式（跨语言）
GENERAL_PATTERNS = [
    # ── Shell 注入 ──
    (re.compile(r"subprocess|os\.system|shell_exec|exec\s*\("), "info", "security",
     "潜在命令执行", "检查此命令执行是否涉及用户输入，以防命令注入。"),
    # ── 路径遍历 ──
    (re.compile(r"(?:\.\./){2,}"), "medium", "security",
     "多层路径遍历", "多个 ../ 可能试图逃逸沙箱目录。使用规范化路径校验。"),
    (re.compile(r"(?:\.\.\\){2,}"), "medium", "security",
     "Windows 路径遍历", "多个 ..\\ 可能试图逃逸目录。使用路径规范化。"),
    # ── 加密 ──
    (re.compile(r"\b(md5|sha1)\s*\(", re.IGNORECASE), "medium", "security",
     "弱哈希算法", "MD5/SHA1 不应用于安全用途。使用 SHA-256+ 系列。"),
    # ── 代码质量 ──
    (re.compile(r"^\s*#\s*noqa\b"), "info", "style",
     "# noqa 抑制检查", "noqa 注释抑制了 lint 检查。确认是有意为之。"),
]


class CodeReviewer:
    """AI 驱动的代码审查引擎（对标 Goose review）。

    用法:
        reviewer = CodeReviewer()
        issues = reviewer.review_file("app.py", content, language="python")
        summary = reviewer.review_summary(issues)

        # 项目级审查
        result = reviewer.project_review("/path/to/project")
    """

    # 静态分析模式表
    PATTERNS = {
        "python": PYTHON_PATTERNS,
        "javascript": JAVASCRIPT_PATTERNS,
        "js": JAVASCRIPT_PATTERNS,
        "typescript": JAVASCRIPT_PATTERNS,
        "ts": JAVASCRIPT_PATTERNS,
        "html": [
            (re.compile(r"\bon\w+\s*=\s*['\"].*\$"), "high", "security",
             "内联事件处理器中拼接变量", "内联事件中拼接用户输入可能导致 XSS。"),
            (re.compile(r"<script\s+[^>]*src\s*=\s*['\"]https?://"), "medium", "security",
             "远程脚本加载", "从外部加载脚本存在供应链风险。使用 SRI 哈希校验。"),
            (re.compile(r"\binnerHTML\s*="), "high", "security",
             "innerHTML 赋值", "HTML 中使用 innerHTML 可能导致 XSS。"),
            (re.compile(r"\bdocument\.write\s*\("), "high", "security",
             "document.write() 调用", "可能导致 DOM 破坏和 XSS。"),
        ],
        "general": GENERAL_PATTERNS,
    }

    # 扩展名到语言的映射
    EXT_TO_LANGUAGE = {
        ".py": "python", ".pyw": "python", ".pyx": "python",
        ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
        ".ts": "typescript", ".tsx": "typescript",
        ".html": "html", ".htm": "html",
    }

    # 语言到文件扩展名的映射
    LANGUAGE_EXTENSIONS = {
        "python": {".py", ".pyw", ".pyx"},
        "javascript": {".js", ".jsx", ".mjs", ".cjs"},
        "typescript": {".ts", ".tsx"},
        "html": {".html", ".htm"},
    }

    def review_file(self, filepath: str, content: str,
                     language: str = "python") -> List[ReviewIssue]:
        """对单个文件运行静态分析。

        Args:
            filepath: 文件路径（用于报告中显示）
            content: 文件内容字符串
            language: 语言类型 (python/javascript/typescript/html)

        Returns:
            ReviewIssue 列表
        """
        issues = []
        # 获取语言特定模式
        patterns = self.PATTERNS.get(language, self.PATTERNS.get("python", []))
        # 同时应用通用模式
        all_patterns = list(patterns) + list(self.PATTERNS.get("general", []))
        lines = content.split("\n")

        for line_num, line in enumerate(lines, 1):
            for pattern, severity, category, title, desc in all_patterns:
                try:
                    if pattern.search(line):
                        issues.append(ReviewIssue(
                            file=filepath, line=line_num,
                            severity=severity, category=category,
                            title=title, description=desc,
                            suggestion=f"第 {line_num} 行: {line.strip()[:80]}"
                        ))
                except Exception:
                    # 正则匹配失败时静默跳过（防止复杂模式导致崩溃）
                    pass

        # Python 额外检查
        if language == "python":
            issues.extend(self._check_function_length(filepath, content))
            issues.extend(self._check_file_length(filepath, len(lines)))
            issues.extend(self._check_mutable_default_args(filepath, content))

        # JavaScript/HTML 额外检查
        if language in ("javascript", "typescript"):
            issues.extend(self._check_file_length(filepath, len(lines)))

        return issues

    def _check_function_length(self, filepath: str, content: str) -> List[ReviewIssue]:
        """检查 Python 函数是否过长（>100行）。"""
        issues = []
        lines = content.split("\n")
        in_func = False
        func_start = 0
        func_indent = 0

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if re.match(r"^(async\s+)?def\s+\w+", stripped):
                in_func = True
                func_start = i
                func_indent = len(line) - len(line.lstrip())
            elif in_func and stripped and len(line) - len(line.lstrip()) <= func_indent and not stripped.startswith("@"):
                func_len = i - func_start
                if func_len > 100:
                    issues.append(ReviewIssue(
                        file=filepath, line=func_start,
                        severity="medium", category="style",
                        title=f"函数过长 ({func_len} 行)",
                        description="过长的函数难以理解和测试。考虑重构为更小的单元。",
                        suggestion=f"拆分从第 {func_start} 行开始的函数"
                    ))
                in_func = False

        # 检查文件末尾未闭合的函数
        if in_func:
            func_len = len(lines) - func_start + 1
            if func_len > 100:
                issues.append(ReviewIssue(
                    file=filepath, line=func_start,
                    severity="medium", category="style",
                    title=f"函数过长 ({func_len} 行)",
                    description="过长的函数难以理解和测试。考虑重构为更小的单元。",
                    suggestion=f"拆分从第 {func_start} 行开始的函数"
                ))

        return issues

    def _check_file_length(self, filepath: str, line_count: int) -> List[ReviewIssue]:
        """检查文件是否过大（>1000行）。"""
        if line_count > 1000:
            return [ReviewIssue(
                file=filepath, severity="low", category="style",
                title=f"文件过大 ({line_count} 行)",
                description="考虑将大文件拆分为多个模块。"
            )]
        return []

    def _check_mutable_default_args(self, filepath: str, content: str) -> List[ReviewIssue]:
        """检查 Python 函数是否使用了可变默认参数（如 def f(x=[])）。"""
        issues = []
        # 匹配 def funcname(...=[] | ={} | =set())
        mutable_pattern = re.compile(
            r"def\s+\w+\s*\([^)]*=\s*(?:\[\s*\]|\{\s*\}|set\s*\(\s*\)|dict\s*\(\s*\)|list\s*\(\s*\))"
        )
        for i, line in enumerate(content.split("\n"), 1):
            if mutable_pattern.search(line):
                issues.append(ReviewIssue(
                    file=filepath, line=i,
                    severity="medium", category="bug",
                    title="可变默认参数",
                    description="可变默认参数 (如 []) 在多次调用间共享状态，可能导致意外行为。",
                    suggestion=f"使用 None 作为默认值，函数体内初始化: def f(x=None): x = x or []"
                ))
        return issues

    # ══════════════════════════════════════════════════════════════════════════
    # 项目级审查
    # ══════════════════════════════════════════════════════════════════════════

    def project_review(self, directory: str, exclude_dirs: Optional[List[str]] = None,
                       file_patterns: Optional[List[str]] = None) -> Dict:
        """扫描整个目录，生成项目级审查汇总报告。

        扫描所有 .py/.js/.ts/.html 文件，按严重度排序所有问题，
        返回包含 issues 列表和统计摘要的字典。

        Args:
            directory: 项目根目录路径
            exclude_dirs: 排除的目录名列表（默认排除 .git, __pycache__, node_modules, venv, .venv）
            file_patterns: 要扫描的文件扩展名列表（默认为所有支持的类型）

        Returns:
            {
                "project": str,           # 项目路径
                "files_scanned": int,      # 扫描文件数
                "total_issues": int,       # 总问题数
                "score": int,              # 评分 0-100
                "verdict": str,            # 结论
                "by_severity": dict,       # 按严重度统计
                "by_category": dict,       # 按类别统计
                "by_file": dict,           # 按文件统计
                "issues": list,            # 所有问题（按严重度排序）
            }
        """
        if exclude_dirs is None:
            exclude_dirs = {".git", "__pycache__", "node_modules", "venv", ".venv",
                            ".tox", ".eggs", "dist", "build", ".mypy_cache",
                            ".pytest_cache", ".ruff_cache", "site-packages"}

        if file_patterns is None:
            file_patterns = [".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm"]

        all_issues: List[ReviewIssue] = []
        files_scanned = 0
        by_file: Dict[str, int] = {}

        directory = os.path.abspath(directory)

        for root, dirs, files in os.walk(directory):
            # 排除指定目录
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]

            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in file_patterns:
                    continue

                filepath = os.path.join(root, filename)
                relpath = os.path.relpath(filepath, directory)

                # 检测语言
                language = self.EXT_TO_LANGUAGE.get(ext, "python")
                if language == "typescript":
                    language = "javascript"  # 复用 JS 模式

                try:
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except (IOError, PermissionError) as e:
                    logger.debug(f"跳过无法读取的文件: {filepath} ({e})")
                    continue

                file_issues = self.review_file(relpath, content, language=language)
                if file_issues:
                    all_issues.extend(file_issues)
                    by_file[relpath] = len(file_issues)

                files_scanned += 1

        # 按严重度排序: critical > high > medium > low > info
        all_issues.sort(key=lambda x: (x.severity_order, x.file, x.line))

        # 生成统计摘要
        summary = self.review_summary(all_issues)
        summary["project"] = directory
        summary["files_scanned"] = files_scanned
        summary["by_file"] = by_file
        summary["issues"] = [i.to_dict() for i in all_issues]

        return summary

    # ══════════════════════════════════════════════════════════════════════════
    # LLM 深度审查（可选，优雅降级）
    # ══════════════════════════════════════════════════════════════════════════

    def ai_deep_review(self, content: str, language: str = "python",
                       model_id: Optional[str] = None) -> Optional[Dict]:
        """使用 LLM 对代码进行深度审查（对标 Goose AI review）。

        如果 LLM 不可用（无模型配置或导入失败），返回 None。
        调用方应检查返回值是否为 None 并优雅降级到静态分析结果。

        Args:
            content: 要审查的代码内容
            language: 编程语言
            model_id: 指定模型 ID（None 表示使用默认模型）

        Returns:
            {
                "summary": str,        # LLM 审查摘要
                "issues": list,        # LLM 发现的问题列表
                "suggestions": str,    # 改进建议
                "model_used": str,     # 使用的模型
                "prompt_tokens": int,  # (可选) 提示 token 数
            }
            或 None（LLM 不可用时）
        """
        try:
            from src.model_registry import get_registry
            reg = get_registry()
            client = reg.get(model_id)
            if not client:
                logger.info("ai_deep_review: 无可用 LLM 模型，跳过深度审查")
                return None

            # 构建审查提示词
            system_prompt = (
                "你是一位资深代码审查专家。请仔细审查以下代码，从安全性、可维护性、"
                "性能、正确性四个维度进行分析。用中文回复。"
            )
            user_prompt = (
                f"请审查以下 {language} 代码:\n\n"
                f"```{language}\n{content[:8000]}\n```\n\n"
                f"请按以下格式回复:\n"
                f"1. 总体评价 (1-2句)\n"
                f"2. 安全问题 (如有)\n"
                f"3. Bug 风险 (如有)\n"
                f"4. 性能问题 (如有)\n"
                f"5. 改进建议\n"
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            resp = client.chat(messages)
            ai_text = resp.get("content", "")

            # 解析 AI 回复
            parsed = self._parse_ai_review(ai_text)

            return {
                "summary": parsed.get("summary", ""),
                "issues": parsed.get("issues", []),
                "suggestions": parsed.get("suggestions", ""),
                "model_used": getattr(client, "model_id", "unknown"),
                "raw_response": ai_text,
            }

        except ImportError:
            logger.info("ai_deep_review: model_registry 不可用，跳过深度审查")
            return None
        except Exception as e:
            logger.warning(f"ai_deep_review: LLM 调用失败 ({e})，回退到静态分析")
            return None

    def _parse_ai_review(self, ai_text: str) -> Dict:
        """解析 LLM 审查回复为结构化数据。"""
        return {
            "summary": ai_text[:500] if ai_text else "",
            "issues": [],
            "suggestions": ai_text if ai_text else "",
        }

    # ══════════════════════════════════════════════════════════════════════════
    # 审查汇总
    # ══════════════════════════════════════════════════════════════════════════

    def review_summary(self, issues: List[ReviewIssue]) -> Dict:
        """生成审查摘要，包含评分和统计。

        Args:
            issues: ReviewIssue 列表

        Returns:
            包含评分、统计、结论的字典
        """
        by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        by_category = {"bug": 0, "security": 0, "style": 0, "performance": 0, "docs": 0}
        for i in issues:
            by_severity[i.severity] = by_severity.get(i.severity, 0) + 1
            by_category[i.category] = by_category.get(i.category, 0) + 1

        # 评分: 满分100，按严重度扣分
        score = max(0, 100
                     - by_severity["critical"] * 15
                     - by_severity["high"] * 8
                     - by_severity["medium"] * 3
                     - by_severity["low"] * 1)

        # 判定
        if score >= 80:
            verdict = "✅ Ready"
        elif score >= 60:
            verdict = "⚠ Review"
        else:
            verdict = "❌ Needs Work"

        return {
            "total_issues": len(issues),
            "score": min(100, score),
            "by_severity": by_severity,
            "by_category": by_category,
            "verdict": verdict,
        }
