"""
Secret红化 + PII检测 — 测试
测试 src/core/secret_scanner.py

覆盖:
- API Key检测 (sk-/api-前缀等)
- Token检测
- 密码检测
- PII: 手机号/身份证/邮箱
- 红化(redact)替换
- 配置文件扫描
"""
import pytest
import tempfile
import os


class TestSecretScanner:
    """Secret + PII 扫描器"""

    def test_detect_openai_key(self):
        """检测OpenAI API Key"""
        from src.core.secret_scanner import SecretScanner
        scanner = SecretScanner()
        matches = scanner.scan("sk-proj-abc123def456ghi789jkl")
        assert len(matches) > 0

    def test_detect_deepseek_key(self):
        """检测DeepSeek API Key"""
        from src.core.secret_scanner import SecretScanner
        scanner = SecretScanner()
        matches = scanner.scan("sk-abc123def456ghi789jkl012mno")
        assert len(matches) > 0

    def test_detect_github_token(self):
        """检测GitHub Token"""
        from src.core.secret_scanner import SecretScanner
        scanner = SecretScanner()
        matches = scanner.scan("ghp_abc123def456ghi789jkl012mno34567pqr")
        assert len(matches) > 0

    def test_detect_aws_key(self):
        """检测AWS Access Key"""
        from src.core.secret_scanner import SecretScanner
        scanner = SecretScanner()
        matches = scanner.scan("AKIAIOSFODNN7EXAMPLE")
        assert len(matches) > 0

    def test_detect_jwt_token(self):
        """检测JWT Token"""
        from src.core.secret_scanner import SecretScanner
        scanner = SecretScanner()
        matches = scanner.scan("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U")
        assert len(matches) > 0

    def test_detect_chinese_phone(self):
        """检测中国手机号"""
        from src.core.secret_scanner import SecretScanner
        scanner = SecretScanner()
        matches = scanner.scan("我的手机是13812345678")
        assert len(matches) > 0

    def test_detect_chinese_id_card(self):
        """检测中国身份证号"""
        from src.core.secret_scanner import SecretScanner
        scanner = SecretScanner()
        matches = scanner.scan("身份证号: 110101199001011234")
        assert len(matches) > 0

    def test_detect_email(self):
        """检测邮箱地址"""
        from src.core.secret_scanner import SecretScanner
        scanner = SecretScanner()
        matches = scanner.scan("联系我: test@example.com")
        assert len(matches) > 0

    def test_redact_replaces_with_mask(self):
        """红化后原文被替换为***"""
        from src.core.secret_scanner import SecretScanner
        scanner = SecretScanner()
        text = "API Key: sk-abc123def456"
        redacted = scanner.redact(text)
        assert "sk-abc123def456" not in redacted
        assert "***" in redacted or "REDACTED" in redacted

    def test_redact_preserves_safe_text(self):
        """红化保留安全文本"""
        from src.core.secret_scanner import SecretScanner
        scanner = SecretScanner()
        text = "Hello World, this is safe text"
        redacted = scanner.redact(text)
        assert "Hello World" in redacted
        assert "safe text" in redacted

    def test_no_match_on_safe_text(self):
        """安全文本不触发检测"""
        from src.core.secret_scanner import SecretScanner
        scanner = SecretScanner()
        matches = scanner.scan("这是一段普通的中文文本")
        assert len(matches) == 0

    def test_scan_file(self, tmp_path):
        """扫描配置文件"""
        from src.core.secret_scanner import SecretScanner
        config = tmp_path / "config.yaml"
        config.write_text("api_key: sk-abc123\npassword: mypass123")
        scanner = SecretScanner()
        findings = scanner.scan_file(str(config))
        assert len(findings) > 0

    def test_redact_from_command(self):
        """命令行中的Secret不泄露"""
        from src.core.secret_scanner import SecretScanner
        scanner = SecretScanner()
        cmd = "curl -H 'Authorization: Bearer sk-abc123def' https://api.com"
        redacted = scanner.redact(cmd)
        assert "sk-abc123def" not in redacted
        assert "Authorization" not in redacted or "Bearer" not in redacted
