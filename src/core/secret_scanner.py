"""
Secret Scanner — 敏感信息检测与红化(Redact)

检测9类敏感信息:
- API Key (OpenAI/DeepSeek)
- GitHub Token
- AWS Access Key
- JWT Token
- Generic API Key (配置文件)
- Bearer Token
- 中国手机号
- 中国身份证号
- 邮箱地址

支持扫描文本和文件, 并提供红化(redact)功能。
"""

import re
import os
from typing import List, Dict, Any, Optional, Set, Tuple


class SecretScanner:
    """Secret + PII 扫描器, 支持检测和红化。"""

    # 检测模式: (正则, 类型标签)
    # 注意: Bearer 排在 OpenAI key 前面, 使得重叠匹配时 Bearer 优先
    #        (Bearer token 的 span 更大, 避免被内嵌的 apikey 先匹配)
    PATTERNS: List[Tuple[str, str]] = [
        # 1. Bearer token — 优先匹配, span 更大
        (r'Bearer\s+[A-Za-z0-9_\-\.]{8,}', 'bearer_token'),
        # 2. GitHub token
        (r'ghp_[A-Za-z0-9]{30,}', 'github_token'),
        # 3. AWS key
        (r'AKIA[A-Z0-9]{16}', 'aws_key'),
        # 4. JWT
        (r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}', 'jwt'),
        # 5. Generic API key (e.g. api_key: xxx / api_key=xxx)
        (r"[a-z]+_api_key[=:]\s*['\"]?\w{20,}", 'api_key'),
        # 6. OpenAI / DeepSeek key
        (r'sk-(?:proj-)?[A-Za-z0-9]{6,}', 'openai_key'),
        # 7. Chinese phone
        (r'1[3-9]\d{9}', 'chinese_phone'),
        # 8. Chinese ID card
        (r'\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]', 'chinese_id'),
        # 9. Email
        (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', 'email'),
    ]

    # scan_file 支持的文件扩展名
    SCANNABLE_EXTENSIONS: Set[str] = {'.env', '.yaml', '.yml', '.json', '.toml', '.py'}

    def scan(self, text: str) -> List[Dict[str, Any]]:
        """扫描文本, 返回检测到的敏感信息列表。

        每条结果包含: type, value, start, end
        """
        all_matches: List[Dict[str, Any]] = []
        for pattern, secret_type in self.PATTERNS:
            for m in re.finditer(pattern, text):
                all_matches.append({
                    'type': secret_type,
                    'value': m.group(),
                    'start': m.start(),
                    'end': m.end(),
                })
        return self._deduplicate(all_matches)

    def redact(self, text: str) -> str:
        """将检测到的敏感信息替换为 [REDACTED:{type}]。"""
        matches = self.scan(text)
        # 从后往前替换, 避免索引偏移
        for match in sorted(matches, key=lambda m: m['start'], reverse=True):
            replacement = f'[REDACTED:{match["type"]}]'
            text = text[:match['start']] + replacement + text[match['end']:]
        return text

    def scan_file(self, path: str) -> List[Dict[str, Any]]:
        """扫描文件中的敏感信息。

        仅扫描 .env / .yaml / .json / .toml / .py 文件。
        返回 findings 列表, 每条包含 file 字段。
        """
        ext = os.path.splitext(path)[1].lower()
        basename = os.path.basename(path)
        # 检查扩展名或完整文件名 (.env 可能无扩展名)
        if ext not in self.SCANNABLE_EXTENSIONS and basename != '.env':
            return []

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (OSError, UnicodeDecodeError, PermissionError):
            return []

        findings = self.scan(content)
        for item in findings:
            item['file'] = path
        return findings

    # ── 内部方法 ──────────────────────────────────────────────

    @staticmethod
    def _deduplicate(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """去重: 移除被其他匹配完全包含的匹配 (保留 span 更大的)。"""
        if not matches:
            return []
        # 按 start 升序, end 降序 (长的优先)
        matches.sort(key=lambda m: (m['start'], -m['end']))
        result: List[Dict[str, Any]] = []
        for m in matches:
            contained = False
            for existing in result:
                if existing['start'] <= m['start'] and m['end'] <= existing['end']:
                    contained = True
                    break
            if not contained:
                result.append(m)
        return result
