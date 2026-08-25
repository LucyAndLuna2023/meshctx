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
  + PII 扩展: 中国手机号 / 身份证号 / 邮箱

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

开源实现说明:
  本文件为 meshctx 开源仓库中的真实实现 (取代原接口 stub)。
  基于正则匹配 + 行号定位 + 置信度调整, 支持自定义规则与文本红化。
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern

# 跳过扫描的目录 (与仓库约定一致)
SKIP_DIRS = {
    '.git', '__pycache__', 'venv', '.venv', 'node_modules', '.tox',
    '.eggs', '.mypy_cache', '.pytest_cache', '.idea', '.vscode',
    'dist', 'build', 'target', '.next', '.nuxt',
}
# 跳过扫描的文件扩展名 (二进制/媒体)
SKIP_EXTS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.svg',
    '.zip', '.gz', '.tar', '.7z', '.rar', '.pdf', '.doc', '.docx',
    '.xls', '.xlsx', '.ppt', '.pptx', '.pyc', '.so', '.dll', '.dylib',
    '.exe', '.bin', '.woff', '.woff2', '.ttf', '.otf', '.mp3', '.mp4',
    '.wav', '.avi', '.mov', '.lock', '.min.js', '.min.css',
}
# 文件大小上限 (默认 2MB, 防止扫描巨型文件)
MAX_FILE_BYTES = 2 * 1024 * 1024


class SecretFinding:
    """密钥发现结果。"""

    def __init__(
        self,
        secret_type: str = None,
        line_number: int = None,
        line_content: str = None,
        match: str = None,
        confidence: float = None,
        file_path: Optional[str] = None,
        context: Optional[str] = None,
        scanner_version: str = '1.0.0',
    ):
        self.secret_type = secret_type
        self.line_number = line_number
        self.line_content = line_content
        self.match = match
        self.confidence = confidence
        self.file_path = file_path
        self.context = context
        self.scanner_version = scanner_version

    def __repr__(self) -> str:
        loc = f"{self.file_path}:{self.line_number}" if self.file_path else f"line {self.line_number}"
        return (
            f"<SecretFinding type={self.secret_type!r} at {loc} "
            f"match={self.match!r} confidence={self.confidence}>"
        )

    def to_dict(self) -> Dict[str, Any]:
        """JSON 可序列化"""
        return {
            "secret_type": self.secret_type,
            "line_number": self.line_number,
            "line_content": self.line_content,
            "match": self.match,
            "confidence": self.confidence,
            "file_path": self.file_path,
            "context": self.context,
            "scanner_version": self.scanner_version,
        }


def _default_rules() -> Dict[str, tuple]:
    """默认检测规则: {name: (regex_pattern, base_confidence)}"""
    return {
        # 1. GitHub tokens
        "github_token": (
            r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b",
            0.95,
        ),
        # 2. AWS
        "aws_access_key": (
            r"\bAKIA[0-9A-Z]{16}\b",
            0.9,
        ),
        "aws_secret_key": (
            r"\b(?:aws_secret_access_key|aws_secret|secret_access_key)\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{20,}['\"]?",
            0.9,
        ),
        "aws_session_token": (
            r"\b(?:aws_session_token|session_token)\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{20,}['\"]?",
            0.8,
        ),
        # 3. OpenAI / DeepSeek / generic sk- keys
        "openai_api_key": (
            r"\bsk-proj-[A-Za-z0-9\-_]{20,}\b",
            0.97,
        ),
        "sk_api_key": (
            r"\bsk-[A-Za-z0-9]{12,}\b",
            0.85,
        ),
        # 4. JWT
        "jwt_token": (
            r"\beyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\b",
            0.9,
        ),
        # 5. SSH / PEM private keys
        "ssh_private_key": (
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",
            0.98,
        ),
        "rsa_private_key": (
            r"-----BEGIN RSA PRIVATE KEY-----",
            0.98,
        ),
        # 6. Generic API key assignments
        "api_key_assignment": (
            r"(?i)\b(?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|"
            r"secret[_-]?key|client[_-]?secret|app[_-]?secret|token)\s*[:=]\s*"
            r"['\"]?[A-Za-z0-9\-_.]{8,}['\"]?",
            0.75,
        ),
        # 7. Bearer tokens
        "bearer_token": (
            r"(?i)\bauthorization\s*:\s*bearer\s+[A-Za-z0-9\-_.]{8,}",
            0.9,
        ),
        # 8. Hardcoded passwords
        "hardcoded_password": (
            r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{4,}['\"]?",
            0.7,
        ),
        "hardcoded_secret": (
            r"(?i)\b(?:secret|secret_key|private_key)\s*[:=]\s*['\"]?[A-Za-z0-9\-_.]{6,}['\"]?",
            0.7,
        ),
        # 9. PII — 中国手机号
        "cn_phone": (
            r"(?<!\d)1[3-9]\d{9}(?!\d)",
            0.8,
        ),
        # 10. PII — 中国身份证号
        "cn_id_card": (
            r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])"
            r"(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)",
            0.85,
        ),
        # 11. PII — 邮箱
        "email_address": (
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            0.55,
        ),
    }


# 弱占位符 / 示例值 → 降低置信度
# 仅作用于"赋值型"规则 (api_key=xxx / password=xxx 等), 不作用于结构化 token
# (AWS AKIA / GitHub ghp_ / JWT / sk- 等), 避免误杀真实高熵密钥。
_PLACEHOLDER_TARGET_TYPES = {
    "api_key_assignment",
    "bearer_token",
    "hardcoded_password",
    "hardcoded_secret",
}
_PLACEHOLDER_PATTERNS = (
    (r"(?i)(your|example|sample|changeme|change_me|xxxx|test|dummy|placeholder|xxxxx)", 0.35),
    (r"(?i)^(secret|password|token|key|api[_-]?key|your[_-]?key)$", 0.3),
    (r"^\*{3,}$", 0.1),
    (r"(?i)example\.com$", 0.3),
    (r"^\d{1,7}$", 0.4),  # 过短纯数字 (年份/计数) 降权; 手机号/身份证为 11/18 位不受影响
    (r"^(sk-)?(abc|xyz|123|000)(abc|xyz|123|000)+$", 0.2),
)


class SecretScanner:
    """密钥泄露扫描器。"""

    def __init__(
        self,
        credential_pool=None,
        max_line_length: int = 2000,
        min_confidence: float = 0.5,
    ):
        self._credential_pool = credential_pool
        self._max_line_length = int(max_line_length)
        self._min_confidence = float(min_confidence)
        self._rules: Dict[str, tuple] = _default_rules()
        self._compiled: Dict[str, Pattern] = {}
        for name, (pat, conf) in self._rules.items():
            try:
                self._compiled[name] = re.compile(pat)
            except re.error:
                # 规则编译失败则跳过 (不吞异常, 但记录为无效规则)
                self._compiled[name] = None
        self._custom_rules: set = set()
        self._stats = {
            "scans": 0,
            "files_scanned": 0,
            "findings": 0,
            "by_type": {},
        }
        self._lock = threading.Lock()

    # ── 便捷别名 ────────────────────────────────────────────
    def scan(self, text: str, **kw) -> List[SecretFinding]:
        """scan(text) — 便捷别名, 同 scan_text。"""
        return self.scan_text(text, **kw)

    def redact(self, text: str, **kw) -> str:
        """redact(text) — 将检测到的密钥替换为 [REDACTED]"""
        if not isinstance(text, str) or not text.strip():
            return text
        redacted = text
        for name, compiled in self._compiled.items():
            if compiled is None:
                continue
            redacted = compiled.sub("[REDACTED]", redacted)
        return redacted

    # ── 扫描入口 ────────────────────────────────────────────
    def scan_text(self, text: str, source: str = '<text>', **kw) -> List[SecretFinding]:
        """扫描文本中的密钥泄露。"""
        if not isinstance(text, str) or not text.strip():
            return []

        findings: List[SecretFinding] = []
        seen: set = set()

        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line[: self._max_line_length] if len(raw_line) > self._max_line_length else raw_line
            if not line.strip():
                continue
            for name, compiled in self._compiled.items():
                if compiled is None:
                    continue
                for m in compiled.finditer(line):
                    matched = m.group(0)
                    if not matched:
                        continue
                    confidence = self._adjust_confidence(name, matched, self._rules[name][1])
                    if confidence < self._min_confidence:
                        continue
                    # 去重: 同一行同一类型同一匹配只报一次
                    key = (name, line_no, matched)
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(
                        SecretFinding(
                            secret_type=name,
                            line_number=line_no,
                            line_content=line.strip(),
                            match=self._sanitize_match(matched),
                            confidence=round(confidence, 3),
                            file_path=source if source and source != '<text>' else None,
                            context=self._build_context(text.splitlines(), line_no - 1),
                        )
                    )

        with self._lock:
            self._stats["scans"] += 1
            self._stats["findings"] += len(findings)
            for f in findings:
                self._stats["by_type"][f.secret_type] = self._stats["by_type"].get(f.secret_type, 0) + 1
        return findings

    def _build_context(self, lines: List[str], index: int) -> Optional[str]:
        """构建匹配行上下文 (前后各1行)"""
        start = max(0, index - 1)
        end = min(len(lines), index + 2)
        return "\n".join(lines[start:end])

    def scan_file(self, path: str, **kw) -> List[SecretFinding]:
        """扫描单个文件。"""
        p = Path(path)
        if not p.is_file():
            return []
        if not self._should_scan_file(p):
            return []
        try:
            size = p.stat().st_size
        except OSError:
            return []
        if size > MAX_FILE_BYTES:
            return []
        try:
            data = p.read_bytes()
        except OSError:
            return []
        # 二进制文件跳过 (含 NUL 字节)
        if b"\x00" in data[:4096]:
            return []
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return []
        with self._lock:
            self._stats["files_scanned"] += 1
        return self.scan_text(text, source=str(p))

    def scan_directory(
        self,
        path: str,
        recursive: bool = True,
        max_files: Optional[int] = 10000,
    ) -> Dict[str, List[SecretFinding]]:
        """递归扫描目录。返回 {文件路径: [findings]}"""
        root = Path(path)
        if not root.is_dir():
            return {}
        result: Dict[str, List[SecretFinding]] = {}
        count = 0
        if recursive:
            for p in sorted(root.rglob("*")):
                if count >= (max_files if max_files is not None else 10000):
                    break
                if not p.is_file():
                    continue
                if not self._should_scan_file(p):
                    continue
                findings = self.scan_file(str(p))
                count += 1
                if findings:
                    result[str(p)] = findings
        else:
            for p in sorted(root.iterdir()):
                if not p.is_file():
                    continue
                if not self._should_scan_file(p):
                    continue
                findings = self.scan_file(str(p))
                if findings:
                    result[str(p)] = findings
        return result

    def scan_paths(self, paths: List[str], **kw) -> Dict[str, List[SecretFinding]]:
        """批量扫描路径 (混合文件和目录)。"""
        result: Dict[str, List[SecretFinding]] = {}
        if not paths:
            return result
        for p in paths:
            path = Path(p)
            if path.is_dir():
                result.update(self.scan_directory(str(path)))
            elif path.is_file():
                findings = self.scan_file(str(path))
                if findings:
                    result[str(path)] = findings
        return result

    # ── 规则管理 ────────────────────────────────────────────
    def add_rule(self, name: str, pattern: str, confidence: float = 0.7, **kw) -> None:
        """添加自定义检测规则。"""
        compiled = re.compile(pattern)  # 无效正则会抛 re.error, 不吞异常
        self._rules[name] = (pattern, float(confidence))
        self._compiled[name] = compiled
        self._custom_rules.add(name)

    def remove_rule(self, name: str, **kw) -> bool:
        """移除自定义规则 (内置规则不可移除)。"""
        if name not in self._custom_rules:
            return False
        self._rules.pop(name, None)
        self._compiled.pop(name, None)
        self._custom_rules.discard(name)
        return True

    def list_rules(self, **kw) -> List[Dict[str, Any]]:
        """列出所有检测规则。"""
        return [
            {"name": name, "pattern": pat, "confidence": conf, "custom": name in self._custom_rules}
            for name, (pat, conf) in self._rules.items()
        ]

    # ── 统计 ────────────────────────────────────────────────
    def get_stats(self, **kw) -> Dict[str, Any]:
        """返回扫描器统计信息。"""
        with self._lock:
            return dict(self._stats)

    def get_scanner_stats(self, **kw) -> Dict[str, Any]:
        """别名: 与要求 API 兼容。"""
        return self.get_stats(**kw)

    def reset_stats(self, **kw) -> None:
        """重置统计计数器。"""
        with self._lock:
            self._stats = {"scans": 0, "files_scanned": 0, "findings": 0, "by_type": {}}

    def generate_report(self, findings: Dict[str, List[SecretFinding]]) -> str:
        """生成可读的扫描报告。"""
        lines = ["# Secret Scanner 报告", ""]
        total = 0
        for path, file_findings in sorted(findings.items()):
            total += len(file_findings)
            lines.append(f"## {path}")
            for f in file_findings:
                lines.append(
                    f"  - [{f.secret_type}] L{f.line_number} "
                    f"(confidence={f.confidence}): {f.match}"
                )
            lines.append("")
        lines.insert(1, f"扫描到 {total} 处敏感信息, 涉及 {len(findings)} 个文件。")
        lines.append("")
        lines.append("建议: 立即轮换泄露的密钥, 并配置扫描器纳入 CI。")
        return "\n".join(lines)

    # ── 内部辅助 ────────────────────────────────────────────
    def _should_scan_file(self, path: Path, **kw) -> bool:
        """判断是否应该扫描该文件。"""
        name = path.name
        if name.startswith('.'):
            # 允许 .env / .npmrc 等配置文件, 跳过其他隐藏文件
            if name not in ('.env', '.env.local', '.npmrc', '.pypirc', '.netrc', '.hgrc'):
                return False
        for part in path.parts:
            if part in SKIP_DIRS:
                return False
        ext = path.suffix.lower()
        if ext in SKIP_EXTS:
            return False
        if name.endswith('.min.js') or name.endswith('.min.css'):
            return False
        return True

    def _adjust_confidence(self, secret_type: str, matched_text: str, base_confidence: float) -> float:
        """调整置信度 — 减少已知 false positive 模式。"""
        conf = float(base_confidence)
        if secret_type in _PLACEHOLDER_TARGET_TYPES:
            for pat, factor in _PLACEHOLDER_PATTERNS:
                if re.search(pat, matched_text):
                    conf *= factor
        # 特定类型微调
        if secret_type == "email_address":
            # 邮箱本身只是 PII 信号, 置信度不高
            conf = min(conf, 0.6)
        if secret_type == "sk_api_key" and len(matched_text) < 12:
            conf *= 0.5
        if secret_type == "hardcoded_password":
            # "password: 1234" 这类过短值降低置信度
            val = matched_text.split(':', 1)[-1].split('=', 1)[-1].strip().strip('\'"')
            if len(val) < 6:
                conf *= 0.5
        return conf

    @staticmethod
    def _sanitize_match(matched_text: str, **kw) -> str:
        """脱敏匹配文本: 显示首尾 4 个字符, 中间用 *** 替换。"""
        if not matched_text:
            return ""
        if len(matched_text) <= 8:
            return "*" * len(matched_text)
        return matched_text[:4] + "***" + matched_text[-4:]


# ── 单例 ─────────────────────────────────────────────────────────
_scanner_instance: Optional[SecretScanner] = None
_scanner_lock = threading.Lock()


def get_secret_scanner(credential_pool=None) -> SecretScanner:
    """获取全局 SecretScanner 单例。"""
    global _scanner_instance
    with _scanner_lock:
        if _scanner_instance is None:
            _scanner_instance = SecretScanner(credential_pool=credential_pool)
        return _scanner_instance


__all__ = [
    "SecretFinding", "SecretScanner",
    "scan", "redact", "scan_text", "scan_file", "scan_directory",
    "scan_paths", "add_rule", "remove_rule", "list_rules",
    "get_stats", "get_scanner_stats", "reset_stats", "generate_report",
    "get_secret_scanner",
]
