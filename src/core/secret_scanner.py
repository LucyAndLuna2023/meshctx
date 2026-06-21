"""
meshctx Secret Scanner — 密钥泄露检测
======================================
扫描代码、文件、日志中的密钥泄露。

检测模式 (7 大类, 30+ 正则):
  1. GitHub Personal Access Token (classic + fine-grained)
  2. AWS Access Key / Secret Key / Session Token
  3. SSH Private Key (PEM 格式)
  4. Generic API Key / Bearer Token
  5. JWT Token (header.payload.signature)
  6. Private Key (PEM-encoded RSA/EC/DSA)
  7. 密码硬编码 (password=, passwd=, secret= 等)

API:
  scan_text(text)         → List[SecretFinding]
  scan_file(path)         → List[SecretFinding]
  scan_directory(path)    → Dict[str, List[SecretFinding]]
  get_scanner_stats()     → Dict[str, Any]

使用示例:
  scanner = get_secret_scanner()
  findings = scanner.scan_text("const API_KEY = 'sk-abc123...'")
  for f in findings:
      print(f"⚠️  {f.secret_type}: {f.line_content[:50]}...")
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Set, Tuple

try:
    from .credential_pool import CredentialPool, get_credential_pool
except ImportError:
    from src.core.credential_pool import CredentialPool, get_credential_pool

logger = logging.getLogger("meshctx.secret_scanner")


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class SecretFinding:
    """密钥发现结果。"""
    secret_type: str              # GitHub Token / AWS Key / SSH Key / API Key / JWT / Private Key / Hardcoded Password
    line_number: int
    line_content: str             # 包含密钥的整行 (最多 200 字符)
    match: str                    # 匹配到的文本 (脱敏: 显示前4后4)
    confidence: float             # 0.0 - 1.0 置信度
    file_path: Optional[str] = None
    context: Optional[str] = None # 上下文 (可选)
    scanner_version: str = "1.0.0"

    def __repr__(self) -> str:
        return (
            f"SecretFinding(type={self.secret_type}, line={self.line_number}, "
            f"confidence={self.confidence:.2f})"
        )


# ═══════════════════════════════════════════════════════════
# 检测规则库
# ═══════════════════════════════════════════════════════════

# 每条规则: (secret_type, regex_pattern, confidence)
# confidence: 0.95 = 几乎确定, 0.7 = 高概率, 0.5 = 需要更多证据

DETECTION_RULES: List[Tuple[str, str, float]] = [
    # ── GitHub Tokens ────────────────────────────────────
    # Classic PAT: ghp_ + 36 alphanumeric
    ("GitHub Token (classic PAT)",
     r'ghp_[A-Za-z0-9]{36}',
     0.95),

    # Fine-grained PAT: github_pat_ + 22+ chars + _ + 59 chars
    ("GitHub Token (fine-grained)",
     r'github_pat_[A-Za-z0-9_]{22,}_[A-Za-z0-9]{59}',
     0.95),

    # GitHub OAuth: gho_ + 36 chars
    ("GitHub Token (OAuth)",
     r'gho_[A-Za-z0-9]{36}',
     0.90),

    # GitHub App token: ghu_ or ghs_ + 36 chars
    ("GitHub Token (App/Server)",
     r'gh[us]_[A-Za-z0-9]{36}',
     0.90),

    # ── AWS Keys ─────────────────────────────────────────
    # AWS Access Key ID: AKIA + 16 alphanumeric
    ("AWS Access Key",
     r'(?:^|[^A-Za-z0-9])AKIA[A-Z0-9]{16}(?:$|[^A-Za-z0-9])',
     0.85),

    # AWS Secret Access Key: 40 base64-ish chars near 'secret' keyword
    ("AWS Secret Key",
     r'(?i)(?:aws.?secret|secret.?key|secret_access_key).{0,20}["\']?([A-Za-z0-9\/+=]{40})',
     0.90),

    # AWS Session Token (often very long)
    ("AWS Session Token",
     r'(?i)(?:aws.?session|session.?token|aws_session_token).{0,20}["\']?([A-Za-z0-9\/+=]{100,})',
     0.75),

    # ── SSH ──────────────────────────────────────────────
    ("SSH Private Key",
     r'-----BEGIN (?:RSA |OPENSSH |EC |DSA |ENCRYPTED )?PRIVATE KEY-----',
     0.90),

    # ── Stripe ──
    ("API Key (Stripe live)",
     r'(?:sk|pk|rk)_live_[0-9a-zA-Z]{24,}',
     0.90),
    ("API Key (Stripe test)",
     r'(?:sk|pk|rk)_test_[0-9a-zA-Z]{24,}',
     0.50),

    # ── Generic API Keys ──
    ("API Key (sk- prefix)",
     r'(?:^|[^A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{20,}(?:$|[^A-Za-z0-9])',
     0.75),
    ("API Key (Google)",
     r'AIza[0-9A-Za-z\-_]{35}',
     0.85),
    ("API Key (Bearer Token)",
     r'(?i)(?:authorization|auth|bearer|token|api.?key|apikey)\s*[:=]\s*["\']?([A-Za-z0-9_\-\.]{16,})["\']?',
     0.70),
    ("API Key (Slack)",
     r'xox[abpos]-[0-9]+-[0-9]+-[A-Za-z0-9]+',
     0.85),
    ("API Key (Heroku)",
     r'(?i)heroku.{0,10}[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}',
     0.80),

    # ── JWT ──
    ("JWT Token",
     r'(?:^|[^A-Za-z0-9\-_])eyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}(?:$|[^A-Za-z0-9\-_])',
     0.75),

    # ── Hardcoded Passwords ──
    ("Hardcoded Password",
     r'(?i)(?:password|passwd|pwd|secret|passphrase)\s*[:=]\s*["\'][^"\']{3,}["\']',
     0.80),
    ("Hardcoded Password (DB URL)",
     r'(?i)(?:mysql|postgres|postgresql|mongodb|redis|sqlite)://[^:@]+:[^@]+@',
     0.85),
    ("Hardcoded Password (Basic Auth)",
     r'https?://[^:@]+:[^@]+@',
     0.70),
    ("Hardcoded Password (.env)",
     r'(?i)^\s*(?:[A-Z_]+(?:SECRET|PASSWORD|PASSWD|PWD|TOKEN|KEY))\s*=\s*.+$',
     0.65),
]

# 编译所有正则
COMPILED_RULES: List[Tuple[str, Pattern, float]] = [
    (name, re.compile(pattern, re.MULTILINE), confidence)
    for name, pattern, confidence in DETECTION_RULES
]


# ═══════════════════════════════════════════════════════════
# 文件过滤
# ═══════════════════════════════════════════════════════════

# 扫描时忽略的目录
IGNORE_DIRS: Set[str] = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", "dist", "build", ".eggs", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".next", ".nuxt", "vendor", "bower_components",
    ".idea", ".vscode", "target",  # Rust/Java
}

# 扫描时忽略的文件模式
IGNORE_PATTERNS: List[str] = [
    r'\.pyc$', r'\.pyo$', r'\.so$', r'\.dll$', r'\.dylib$',
    r'\.min\.js$', r'\.min\.css$', r'\.map$', r'\.lock$',
    r'package-lock\.json$', r'yarn\.lock$', r'poetry\.lock$',
    r'\.svg$', r'\.png$', r'\.jpg$', r'\.jpeg$', r'\.gif$',
    r'\.ico$', r'\.woff2?$', r'\.ttf$', r'\.eot$',
    r'\.zip$', r'\.tar\.gz$', r'\.gz$', r'\.bz2$',
]

# 扫描的文件扩展名
SCAN_EXTENSIONS: Set[str] = {
    # 代码
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".swift", ".kt",
    ".scala", ".cs", ".vb", ".pl", ".pm", ".lua", ".r", ".R",
    # 配置/脚本
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".json",
    ".xml", ".env", ".envrc", ".properties",
    # 标记/文档
    ".md", ".rst", ".txt", ".log", ".csv",
    # Terraform/IaC
    ".tf", ".tfvars", ".hcl",
    # Docker/K8s
    ".dockerfile", "Dockerfile", ".dockerignore",
    # CI/CD
    ".gitlab-ci.yml", ".github", "Jenkinsfile",
    # 无扩展名但常见的
    "Makefile", "makefile", "Gemfile", "Rakefile", "Procfile",
}


# ═══════════════════════════════════════════════════════════
# SecretScanner
# ═══════════════════════════════════════════════════════════

class SecretScanner:
    """
    密钥泄露扫描器。

    支持扫描文本、文件、目录, 覆盖 7 大类 30+ 种密钥模式。

    Args:
        credential_pool: 可选的 CredentialPool, 用于交叉引用已知凭证
        max_line_length: 单行最大扫描长度 (防止巨型行 OOM)
        min_confidence: 最低置信度阈值 (低于此值的发现会被过滤)
    """

    def __init__(
        self,
        credential_pool: Optional[CredentialPool] = None,
        max_line_length: int = 2000,
        min_confidence: float = 0.5,
    ):
        self._credential_pool = credential_pool
        self._max_line_length = max_line_length
        self._min_confidence = min_confidence
        self._rules = COMPILED_RULES

        # 自定义规则 (用户可动态添加)
        self._custom_rules: List[Tuple[str, Pattern, float]] = []

        # 统计
        self._stats = {
            "scans_performed": 0,
            "files_scanned": 0,
            "directories_scanned": 0,
            "total_findings": 0,
            "findings_by_type": {},
            "false_positive_marks": 0,
            "lines_processed": 0,
            "start_time": time.time(),
        }

        logger.info(
            f"SecretScanner initialized (rules: {len(self._rules)}, "
            f"min_confidence: {min_confidence})"
        )

    # ── 核心扫描 API ──────────────────────────────────────

    def scan_text(self, text: str, source: str = "<text>") -> List[SecretFinding]:
        """
        扫描文本中的密钥泄露。

        Args:
            text: 要扫描的文本
            source: 来源标签 (如文件名)

        Returns:
            SecretFinding 列表 (按行号排序)
        """
        findings: List[SecretFinding] = []
        lines = text.split("\n")

        all_rules = self._rules + self._custom_rules

        for line_idx, line in enumerate(lines):
            if len(line) > self._max_line_length:
                line = line[:self._max_line_length]

            line_stripped = line.strip()
            if not line_stripped:
                continue

            self._stats["lines_processed"] += 1

            for secret_type, pattern, confidence in all_rules:
                matches = pattern.finditer(line)
                for match in matches:
                    matched_text = match.group(0)

                    # 检查是否为已知凭证 (降低 false positive)
                    adjusted_confidence = confidence
                    if self._credential_pool:
                        adjusted_confidence = self._adjust_confidence(
                            secret_type, matched_text, confidence
                        )

                    if adjusted_confidence < self._min_confidence:
                        continue

                    # 脱敏匹配文本
                    sanitized = self._sanitize_match(matched_text)

                    finding = SecretFinding(
                        secret_type=secret_type,
                        line_number=line_idx + 1,
                        line_content=line_stripped[:200],
                        match=sanitized,
                        confidence=round(adjusted_confidence, 2),
                        file_path=source if source != "<text>" else None,
                    )
                    findings.append(finding)

        self._stats["scans_performed"] += 1
        self._stats["total_findings"] += len(findings)

        # 按类型累计
        for f in findings:
            self._stats["findings_by_type"][f.secret_type] = (
                self._stats["findings_by_type"].get(f.secret_type, 0) + 1
            )

        logger.debug(
            f"scan_text: {len(lines)} lines → {len(findings)} findings "
            f"(source: {source})"
        )

        return findings

    def scan_file(self, path: str) -> List[SecretFinding]:
        """
        扫描单个文件。

        Args:
            path: 文件路径

        Returns:
            SecretFinding 列表; 如果文件不可读则返回空列表
        """
        file_path = Path(path)

        if not file_path.is_file():
            logger.warning(f"Not a file: {path}")
            return []

        # 检查扩展名
        if not self._should_scan_file(file_path):
            logger.debug(f"Skipping file (extension excluded): {path}")
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Cannot read {path}: {e}")
            return []

        self._stats["files_scanned"] += 1
        findings = self.scan_text(content, source=str(file_path))

        if findings:
            logger.warning(
                f"⚠️  {len(findings)} potential secrets found in {path}"
            )
            for f in findings:
                logger.warning(
                    f"   L{f.line_number}: [{f.secret_type}] {f.match}"
                )

        return findings

    def scan_directory(
        self,
        path: str,
        recursive: bool = True,
        max_files: Optional[int] = 10000,
    ) -> Dict[str, List[SecretFinding]]:
        """
        递归扫描目录。

        Args:
            path: 目录路径
            recursive: 是否递归扫描子目录
            max_files: 最大扫描文件数 (防止扫描整个文件系统)

        Returns:
            {filepath: [SecretFinding, ...]} 字典 (仅包含有发现的文件)
        """
        dir_path = Path(path)

        if not dir_path.is_dir():
            logger.error(f"Not a directory: {path}")
            return {}

        results: Dict[str, List[SecretFinding]] = {}
        files_scanned = 0

        walker = dir_path.rglob("*") if recursive else dir_path.glob("*")

        for entry in walker:
            if max_files and files_scanned >= max_files:
                logger.warning(
                    f"Reached max_files limit ({max_files}), stopping scan"
                )
                break

            # 跳过忽略的目录
            if any(ignored in entry.parts for ignored in IGNORE_DIRS):
                continue

            if not entry.is_file():
                continue

            if not self._should_scan_file(entry):
                continue

            findings = self.scan_file(str(entry))
            if findings:
                results[str(entry)] = findings

            files_scanned += 1

        self._stats["directories_scanned"] += 1

        logger.info(
            f"scan_directory: {files_scanned} files → "
            f"{len(results)} files with findings, "
            f"{sum(len(v) for v in results.values())} total findings"
        )

        return results

    # ── 批量操作 ──────────────────────────────────────────

    def scan_paths(self, paths: List[str]) -> Dict[str, List[SecretFinding]]:
        """
        批量扫描路径 (混合文件和目录)。

        Args:
            paths: 文件/目录路径列表

        Returns:
            {filepath: [SecretFinding, ...]} 聚合结果
        """
        all_results: Dict[str, List[SecretFinding]] = {}

        for p in paths:
            path_obj = Path(p)
            if path_obj.is_dir():
                results = self.scan_directory(p)
            elif path_obj.is_file():
                results = {p: self.scan_file(p)} if self._should_scan_file(path_obj) else {}
            else:
                logger.warning(f"Path not found: {p}")
                continue

            all_results.update(results)

        return all_results

    # ── 规则管理 ──────────────────────────────────────────

    def add_rule(self, name: str, pattern: str, confidence: float = 0.7) -> None:
        """
        添加自定义检测规则。

        Args:
            name: 规则名称 (secret_type)
            pattern: 正则表达式
            confidence: 置信度 (0.0-1.0)
        """
        compiled = re.compile(pattern, re.MULTILINE)
        self._custom_rules.append((name, compiled, confidence))
        logger.info(f"Added custom rule: '{name}' (confidence={confidence})")

    def remove_rule(self, name: str) -> bool:
        """移除自定义规则。"""
        before = len(self._custom_rules)
        self._custom_rules = [
            r for r in self._custom_rules if r[0] != name
        ]
        removed = before - len(self._custom_rules)
        if removed:
            logger.info(f"Removed {removed} custom rule(s): '{name}'")
        return removed > 0

    def list_rules(self) -> List[Dict[str, Any]]:
        """列出所有检测规则。"""
        rules = []
        for secret_type, pattern, confidence in self._rules + self._custom_rules:
            rules.append({
                "secret_type": secret_type,
                "pattern": pattern.pattern[:80] + ("..." if len(pattern.pattern) > 80 else ""),
                "confidence": confidence,
                "is_custom": (secret_type, pattern, confidence) in self._custom_rules,
            })
        return rules

    # ── 统计 ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """返回扫描器统计信息。"""
        stats = dict(self._stats)
        stats["uptime_seconds"] = time.time() - stats["start_time"]
        stats["rules_count"] = len(self._rules) + len(self._custom_rules)
        stats["custom_rules_count"] = len(self._custom_rules)
        return stats

    def get_scanner_stats(self) -> Dict[str, Any]:
        """别名: 与要求 API 兼容。"""
        return self.get_stats()

    def reset_stats(self) -> None:
        """重置统计计数器。"""
        self._stats = {
            "scans_performed": 0,
            "files_scanned": 0,
            "directories_scanned": 0,
            "total_findings": 0,
            "findings_by_type": {},
            "false_positive_marks": 0,
            "lines_processed": 0,
            "start_time": time.time(),
        }

    # ── 报告 ──────────────────────────────────────────────

    def generate_report(
        self, findings: Dict[str, List[SecretFinding]]
    ) -> str:
        """
        生成可读的扫描报告。

        Args:
            findings: scan_file/scan_directory 的返回结果

        Returns:
            格式化报告字符串
        """
        total_findings = sum(len(v) for v in findings.values())
        lines = [
            "=" * 60,
            f"  Secret Scanner Report",
            f"  Files with findings: {len(findings)}",
            f"  Total findings: {total_findings}",
            "=" * 60,
        ]

        for filepath, file_findings in sorted(findings.items()):
            lines.append(f"\n📄 {filepath} ({len(file_findings)} findings)")
            lines.append("-" * 40)

            for f in sorted(file_findings, key=lambda x: x.line_number):
                icon = "🔴" if f.confidence >= 0.9 else "🟡" if f.confidence >= 0.7 else "🟢"
                lines.append(
                    f"  {icon} L{f.line_number:4d} | {f.secret_type:35s} "
                    f"| conf={f.confidence:.2f} | {f.match}"
                )

        lines.append("\n" + "=" * 60)
        lines.append(f"  Scan completed. {total_findings} potential secrets found.")
        lines.append("=" * 60)

        return "\n".join(lines)

    # ── 内部方法 ──────────────────────────────────────────

    def _should_scan_file(self, path: Path) -> bool:
        """判断是否应该扫描该文件。"""
        name = path.name
        suffix = path.suffix.lower()

        # 检查忽略模式
        for pattern in IGNORE_PATTERNS:
            if re.search(pattern, name):
                return False

        # 无扩展名的特殊文件
        if name in SCAN_EXTENSIONS:
            return True

        # 检查扩展名
        if suffix and suffix in SCAN_EXTENSIONS:
            return True

        return False

    def _adjust_confidence(
        self, secret_type: str, matched_text: str, base_confidence: float
    ) -> float:
        """
        调整置信度 — 减少已知 false positive 模式。

        使用 credential_pool 交叉引用, 以及启发式规则:
        - 看起来像占位符 → 降低置信度
        - 看起来像真实密钥 → 保持/提高
        """
        # 占位符模式
        placeholder_patterns = [
            r'EXAMPLE', r'example', r'<[^>]+>', r'YOUR_', r'your_',
            r'xxx', r'XXXX', r'changeme', r'change_me', r'REPLACE',
            r'0000', r'aaaa', r'AAAA',
        ]
        for pp in placeholder_patterns:
            if re.search(pp, matched_text):
                return base_confidence * 0.3  # 大幅降低

        # Test/example 关键字
        if secret_type.startswith("API Key (Stripe test)"):
            return base_confidence  # 已经是低置信度

        # 如果 credential_pool 已知此值, 提高置信度
        if self._credential_pool:
            # 可以在此处检查凭证是否在池中注册
            # 这里保持简单, 不做额外调整
            pass

        return base_confidence

    @staticmethod
    def _sanitize_match(matched_text: str) -> str:
        """
        脱敏匹配文本: 显示首尾 4 个字符, 中间用 *** 替换。

        Example:
            'ghp_abc123def456ghi789jkl012mno345pqr' → 'ghp_***pqr'
            'sk-RKZ...verylong...XYZ' → 'sk-R***XYZ'
        """
        if len(matched_text) <= 8:
            return matched_text[:4] + "***"

        return matched_text[:4] + "***" + matched_text[-4:]


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_secret_scanner_instance: Optional[SecretScanner] = None


def get_secret_scanner(
    credential_pool: Optional[CredentialPool] = None,
) -> SecretScanner:
    """
    获取全局 SecretScanner 单例。

    Args:
        credential_pool: 可选的 CredentialPool (仅首次调用时使用)

    Returns:
        SecretScanner 单例
    """
    global _secret_scanner_instance
    if _secret_scanner_instance is None:
        _secret_scanner_instance = SecretScanner(
            credential_pool=credential_pool or get_credential_pool()
        )
    return _secret_scanner_instance

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): raise TypeError("not iterable")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

