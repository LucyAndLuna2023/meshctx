"""
BrowserCookieVault 单测 — Fernet 加密持久化 / 换机失效 / 清理
"""
import asyncio

import pytest

from src.core.browser_cookie_vault import BrowserCookieVault

COOKIES = [
    {"name": "session", "value": "s3cr3t", "domain": ".x.com", "path": "/"},
    {"name": "csrf", "value": "tok", "domain": ".github.com", "path": "/"},
]


async def _roundtrip(tmp_path):
    vault = BrowserCookieVault(path=str(tmp_path / "vault.enc"))
    await vault.save(COOKIES)
    return vault


@pytest.mark.asyncio
async def test_save_then_load(tmp_path):
    vault = await _roundtrip(tmp_path)
    loaded = await vault.load()
    assert loaded == COOKIES


@pytest.mark.asyncio
async def test_encrypted_at_rest(tmp_path):
    vault = await _roundtrip(tmp_path)
    raw = (tmp_path / "vault.enc").read_bytes()
    # 明文不应出现
    assert b"s3cr3t" not in raw
    assert b"session" not in raw


@pytest.mark.asyncio
async def test_wrong_key_fails(tmp_path):
    """密钥从 machine-id 派生 → 密钥失效时 save 拒绝落盘 (换机失效保护)"""
    class WrongKeyVault(BrowserCookieVault):
        def _derive_key(self) -> bytes:
            return b"x" * 32  # 无效 Fernet key

    vault = WrongKeyVault(path=str(tmp_path / "vault.enc"))
    saved = await vault.save(COOKIES)
    assert saved is False          # 密钥无效 → 拒绝落盘
    assert not vault.exists        # 无文件残留


@pytest.mark.asyncio
async def test_clear_removes_file(tmp_path):
    vault = await _roundtrip(tmp_path)
    assert vault.exists
    await vault.clear()
    assert not vault.exists
    assert await vault.load() == []


@pytest.mark.asyncio
async def test_load_missing_returns_empty(tmp_path):
    vault = BrowserCookieVault(path=str(tmp_path / "nope.enc"))
    assert await vault.load() == []


@pytest.mark.asyncio
async def test_get_cookie_vault_singleton():
    from src.core.browser_cookie_vault import get_cookie_vault
    assert get_cookie_vault() is get_cookie_vault()
