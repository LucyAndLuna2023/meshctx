# -*- coding: utf-8 -*-
"""v3.131.5 回归守门: API Key 非 ASCII 防御 (002codex v3.131.5 审计 P2 finding)。

用户场景: Mac zhipu 配置粘贴混入非 ASCII 字符 → httpx 构造 Authorization 头
报晦涩的 "ascii codec can't encode character in position 9-10: ordinal not in
range(128)"。修复后要求: ①不可见字符剥离 ②仍含非 ASCII 时报可定位错误
(位置+U+码点+重粘指引)。

覆盖三层: model_registry._sanitize_api_key / model_adapter._sanitize_secret /
crypto.decrypt_key (UnicodeEncodeError → 可读 ValueError)。
"""
import pytest


# ── model_registry._sanitize_api_key ─────────────────────

def test_registry_sanitize_clean_key_passthrough():
    from src.model_registry import _sanitize_api_key
    assert _sanitize_api_key("sk-abc123.def456", "zhipu:glm-4.5") == "sk-abc123.def456"


def test_registry_sanitize_strips_invisible_chars():
    from src.model_registry import _sanitize_api_key
    # 零宽空格/BOM/全角空格/软连字符 均剥离
    assert _sanitize_api_key("sk-a\u200bbc", "m") == "sk-abc"
    assert _sanitize_api_key("\ufeffsk-abc", "m") == "sk-abc"
    assert _sanitize_api_key("sk\u00a0-abc", "m") == "sk-abc"
    assert _sanitize_api_key("sk\u00ad-abc", "m") == "sk-abc"


def test_registry_sanitize_non_ascii_raises_locatable_error():
    """核心回归: ab中文.def → 位置2(U+4E2D),位置3(U+6587) — 与线上 ascii 9-10 闭环。"""
    from src.model_registry import _sanitize_api_key
    with pytest.raises(ValueError) as ei:
        _sanitize_api_key("ab中文.def", "zhipu:glm-4.5")
    msg = str(ei.value)
    assert "位置2(U+4E2D)" in msg and "位置3(U+6587)" in msg
    assert "zhipu:glm-4.5" in msg  # 含模型名便于定位
    assert "重新复制" in msg       # 含修复指引


def test_registry_sanitize_sample_cap_and_none_safe():
    """round44 P4-1: 错误样本上限 5 处 (7 个非 ASCII 只报前 5) + None 安全。"""
    from src.model_registry import _sanitize_api_key
    with pytest.raises(ValueError) as ei:
        _sanitize_api_key("中" * 7, "m")
    msg = str(ei.value)
    for i in range(5):
        assert f"位置{i}(U+4E2D)" in msg
    assert "位置5" not in msg          # bad[:5] 截断
    assert _sanitize_api_key(None, "m") == ""


def test_registry_sanitize_base_url_non_ascii_raises():
    from src.model_registry import _sanitize_base_url
    assert _sanitize_base_url("https://open.bigmodel.cn/api/paas/v4/", "m") == \
        "https://open.bigmodel.cn/api/paas/v4"  # rstrip('/')
    with pytest.raises(ValueError):
        _sanitize_base_url("https://中文.example.com", "m")


# ── model_adapter._sanitize_secret ───────────────────────

def test_adapter_sanitize_secret_clean_passthrough_and_strip():
    from src.model_adapter import _sanitize_secret
    assert _sanitize_secret("sk-xyz") == "sk-xyz"
    assert _sanitize_secret("  sk-xyz\u200b  ") == "sk-xyz"


def test_adapter_sanitize_secret_non_ascii_raises():
    from src.model_adapter import _sanitize_secret
    with pytest.raises(ValueError) as ei:
        _sanitize_secret("id秘.secret", "base_url")
    assert "U+79D8" in str(ei.value)  # 秘


# ── crypto.decrypt_key 损坏密文 ──────────────────────────

def test_crypto_decrypt_corrupt_cipher_non_ascii_raises_readable():
    """enc: 前缀后含非 ASCII → 可读 ValueError 而非 ascii codec 堆栈。"""
    from src.core.crypto import decrypt_key
    with pytest.raises(ValueError) as ei:
        decrypt_key("enc:abc中def")
    assert "密文损坏" in str(ei.value)
    assert "U+4E2D" in str(ei.value)


def test_crypto_decrypt_plain_key_passthrough():
    """无前缀明文 key 原样返回 (向后兼容)。"""
    from src.core.crypto import decrypt_key
    assert decrypt_key("sk-plain-key") == "sk-plain-key"
