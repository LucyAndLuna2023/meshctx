"""
MeshCtx Browser Cookie Vault — 浏览器 Cookie 加密持久化 (v3.117 P1)

安全模型:
  · Fernet 对称加密 (cryptography 库, 已依赖)
  · 密钥派生: PBKDF2-HMAC-SHA256(machine-id + salt) → 本机绑定
  · 存储: ~/.meshctx/browser_cookies.enc (0600 权限)
  · 授权时注入浏览器, revoke 时可选清除

用法:
    vault = BrowserCookieVault()
    cookies = await vault.load()          # 解密读取
    await vault.save(cookies)             # 加密写入
    await vault.clear()                   # 清除文件
"""
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.cookie_vault")

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    Fernet = None
    InvalidToken = Exception

VAULT_DIR = Path.home() / ".meshctx"
VAULT_FILE = VAULT_DIR / "browser_cookies.enc"
SALT_FILE = VAULT_DIR / "browser_salt"
_PBKDF2_ITERATIONS = 390_000


class BrowserCookieVault:
    """Cookie 加密持久化 — 本机绑定, 授权时加载"""

    def __init__(self, path=None):
        self._path = Path(path) if path else VAULT_FILE
        self._salt_path = self._path.with_name("browser_salt")
        self._fernet: Optional[Any] = None
        self._machine_id = self._get_machine_id()

    # ── 密钥派生 ──────────────────────────────────────
    def _get_machine_id(self) -> str:
        """机器标识: 优先 machine-id, 回退 hostname+用户名"""
        candidates = [
            "/etc/machine-id",
            "/var/lib/dbus/machine-id",
            "/etc/hostname",
        ]
        for c in candidates:
            try:
                p = Path(c)
                if p.exists():
                    return p.read_text().strip()
            except Exception:
                continue
        import socket
        return f"{socket.gethostname()}:{os.getenv('USER', '')}"

    def _derive_key(self) -> bytes:
        """PBKDF2 派生 Fernet key (本机绑定)"""
        if Fernet is None:
            raise RuntimeError("需要安装: pip install cryptography")

        salt = self._get_or_create_salt()
        raw = hashlib.pbkdf2_hmac(
            "sha256",
            self._machine_id.encode(),
            salt,
            _PBKDF2_ITERATIONS,
            dklen=32,
        )
        import base64
        return base64.urlsafe_b64encode(raw)

    def _get_or_create_salt(self) -> bytes:
        if self._salt_path.exists():
            return self._salt_path.read_bytes()
        self._salt_path.parent.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(16)
        self._salt_path.write_bytes(salt)
        try:
            os.chmod(self._salt_path, 0o600)
        except Exception:
            pass
        return salt

    def _ensure_fernet(self):
        if self._fernet is None:
            self._fernet = Fernet(self._derive_key())

    # ── 加解密 ────────────────────────────────────────
    def encrypt(self, data: Dict[str, Any]) -> str:
        """加密任意 dict → token 字符串"""
        self._ensure_fernet()
        return self._fernet.encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()

    def decrypt(self, token: str) -> Dict[str, Any]:
        """解密 token → dict (token 无效返回 {})"""
        self._ensure_fernet()
        try:
            raw = self._fernet.decrypt(token.encode())
            return json.loads(raw)
        except (InvalidToken, Exception):
            logger.warning("Cookie vault: token 解密失败 (可能换机/换用户)")
            return {}

    # ── 持久化 ────────────────────────────────────────
    async def load(self) -> List[Dict[str, Any]]:
        """读取并解密 cookie 列表"""
        if not self._path.exists():
            return []
        try:
            token = self._path.read_text().strip()
            data = self.decrypt(token)
            return data.get("cookies", [])
        except Exception as e:
            logger.error(f"Cookie vault load 失败: {e}")
            return []

    async def save(self, cookies: List[Dict[str, Any]]) -> bool:
        """加密并写入 cookie 列表"""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            token = self.encrypt({"cookies": cookies, "v": 1})
            self._path.write_text(token)
            os.chmod(self._path, 0o600)
            return True
        except Exception as e:
            logger.error(f"Cookie vault save 失败: {e}")
            return False

    async def clear(self) -> bool:
        """删除加密文件 (revoke 时调用)"""
        try:
            if self._path.exists():
                self._path.unlink()
            return True
        except Exception as e:
            logger.error(f"Cookie vault clear 失败: {e}")
            return False

    @property
    def exists(self) -> bool:
        return self._path.exists()


# 全局单例
_vault: Optional[BrowserCookieVault] = None


def get_cookie_vault() -> BrowserCookieVault:
    global _vault
    if _vault is None:
        _vault = BrowserCookieVault()
    return _vault


def reset_cookie_vault():
    global _vault
    _vault = None
