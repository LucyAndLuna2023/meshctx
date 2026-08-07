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
# NOTE: 本文件为 meshctx 开源接口 stub。核心实现位于私有仓库 meshctx-core。
# 商业/完整版: pip install meshctx-core (需授权)。访问接口将抛 NotImplementedError。
from __future__ import annotations
from enum import Enum
from abc import ABC
__all__ = []

class _MeshCtxStubProxy:
    """未导出符号的优雅降级代理: 导入成功, 调用/属性访问时提示需 meshctx-core。"""
    def __init__(self, name):
        self._name = name
    def __getattr__(self, attr):
        return _MeshCtxStubProxy(f"{self._name}.{attr}")
    def __call__(self, *args, **kwargs):
        raise NotImplementedError(f"meshctx-core required (private repo): {self._name}")
    def __repr__(self):
        return f"<meshctx stub {self._name}>"

def __getattr__(name):
    return _MeshCtxStubProxy(name)

__all__ = []
__all__ = []
__all__ = []
class SecretFinding:
    """密钥发现结果。"""
    def __repr__(self) -> str:
        raise NotImplementedError("meshctx-core required (private repo)")


class SecretScanner:
    """密钥泄露扫描器。"""
    def __init__(self, credential_pool = None, max_line_length: int = 2000, min_confidence: float = 0.5):
        raise NotImplementedError("meshctx-core required (private repo)")

    def scan(self, text: str, **kw) -> List[SecretFinding]:
        """scan(text) — 便捷别名, 同 scan_text。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def redact(self, text: str, **kw) -> str:
        """redact(text) — 将检测到的密钥替换为 [REDACTED]"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def scan_text(self, text: str, source: str = '<text>', **kw) -> List[SecretFinding]:
        """扫描文本中的密钥泄露。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def scan_file(self, path: str, **kw) -> List[SecretFinding]:
        """扫描单个文件。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def scan_directory(self, path: str, recursive: bool = True, max_files: Optional[int] = 10000) -> Dict[str, List[SecretFinding]]:
        """递归扫描目录。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def scan_paths(self, paths: List[str], **kw) -> Dict[str, List[SecretFinding]]:
        """批量扫描路径 (混合文件和目录)。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def add_rule(self, name: str, pattern: str, confidence: float = 0.7, **kw) -> None:
        """添加自定义检测规则。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def remove_rule(self, name: str, **kw) -> bool:
        """移除自定义规则。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def list_rules(self, **kw) -> List[Dict[str, Any]]:
        """列出所有检测规则。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def get_stats(self, **kw) -> Dict[str, Any]:
        """返回扫描器统计信息。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def get_scanner_stats(self, **kw) -> Dict[str, Any]:
        """别名: 与要求 API 兼容。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def reset_stats(self, **kw) -> None:
        """重置统计计数器。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def generate_report(self, findings: Dict[str, List[SecretFinding]]) -> str:
        """生成可读的扫描报告。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def _should_scan_file(self, path: Path, **kw) -> bool:
        """判断是否应该扫描该文件。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def _adjust_confidence(self, secret_type: str, matched_text: str, base_confidence: float) -> float:
        """调整置信度 — 减少已知 false positive 模式。"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def _sanitize_match(matched_text: str, **kw) -> str:
        """脱敏匹配文本: 显示首尾 4 个字符, 中间用 *** 替换。"""
        raise NotImplementedError("meshctx-core required (private repo)")


def get_secret_scanner(credential_pool = None) -> SecretScanner:
    """获取全局 SecretScanner 单例。"""
    raise NotImplementedError("meshctx-core required (private repo)")

