"""
meshctx v2.20 — 自动更新检测模块
检查GitHub Releases最新版本 + 提供下载/升级信息

架构: GitHub API → 版本对比 → 更新通知
无外部依赖(仅用urllib,标准库)
"""
import json
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any
from packaging.version import Version, InvalidVersion

logger = logging.getLogger("meshctx.autoupdate")

# ── 配置 ──
GITHUB_API = "https://api.github.com/repos/LucyAndLuna2023/meshctx/releases/latest"
GITHUB_TOKEN = None  # 可选, 提升API限流(60→5000次/小时)
UPDATE_CACHE_FILE = Path.home() / ".meshctx" / "update_cache.json"
CACHE_TTL = 3600  # 1小时缓存


def _get_github_token() -> Optional[str]:
    """从配置文件读取GitHub Token(可选)"""
    global GITHUB_TOKEN
    if GITHUB_TOKEN:
        return GITHUB_TOKEN
    try:
        import yaml
        config_file = Path.home() / ".meshctx" / "config.yaml"
        if config_file.exists():
            with open(config_file) as f:
                config = yaml.safe_load(f) or {}
            GITHUB_TOKEN = config.get("github", {}).get("token")
    except Exception:
        pass
    return GITHUB_TOKEN


def _make_request(url: str) -> Optional[dict]:
    """发送GitHub API请求"""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "meshctx-autoupdate/2.0",
    }
    token = _get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        logger.warning(f"GitHub API HTTP {e.code}: {e.reason}")
        return None
    except Exception as e:
        logger.warning(f"GitHub API 请求失败: {e}")
        return None


def _read_cache() -> Optional[dict]:
    """读取更新缓存"""
    try:
        if UPDATE_CACHE_FILE.exists():
            import time
            data = json.loads(UPDATE_CACHE_FILE.read_text())
            if time.time() - data.get("cached_at", 0) < CACHE_TTL:
                return data
    except Exception:
        pass
    return None


def _write_cache(data: dict):
    """写入更新缓存"""
    try:
        import time
        data["cached_at"] = time.time()
        UPDATE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        UPDATE_CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False))
    except Exception:
        pass


def _parse_version(version_str: str) -> Optional[Version]:
    """安全解析版本号"""
    try:
        # 移除v前缀
        v = version_str.lstrip("v")
        return Version(v)
    except (InvalidVersion, TypeError):
        return None


def check_update(current_version: str) -> Optional[Dict[str, Any]]:
    """
    检查是否有新版本可用
    
    Args:
        current_version: 当前版本号 (如 "2.19.0")
    
    Returns:
        {
            "update_available": bool,
            "current_version": str,
            "latest_version": str,
            "release_url": str,
            "release_notes": str,
            "published_at": str,
            "assets": [...],  # 下载链接
            "download_urls": {...}  # 按平台分组的下载链接
        }
    """
    # 检查缓存
    cached = _read_cache()
    if cached and "latest_version" in cached:
        latest_v = _parse_version(cached["latest_version"])
        current_v = _parse_version(current_version)
        if latest_v and current_v:
            return {
                "update_available": latest_v > current_v,
                "current_version": current_version,
                "latest_version": cached["latest_version"],
                "release_url": cached.get("release_url", ""),
                "release_notes": cached.get("release_notes", ""),
                "published_at": cached.get("published_at", ""),
                "assets": cached.get("assets", []),
                "download_urls": cached.get("download_urls", {}),
                "cached": True,
            }

    # 请求GitHub API
    data = _make_request(GITHUB_API)
    if not data:
        return {
            "error": "无法获取最新版本信息",
            "current_version": current_version,
            "hint": "检查网络连接或配置 github.token",
        }

    latest_tag = data.get("tag_name", "")
    latest_v = _parse_version(latest_tag)
    current_v = _parse_version(current_version)

    # 解析assets
    assets = []
    download_urls = {}
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        url = asset.get("browser_download_url", "")
        size = asset.get("size", 0)
        assets.append({
            "name": name,
            "url": url,
            "size": size,
            "size_mb": round(size / 1024 / 1024, 1) if size else 0,
        })
        # 按平台分类
        if ".dmg" in name or "macos" in name.lower():
            download_urls["macos"] = url
        elif ".exe" in name or "setup" in name.lower():
            if "portable" in name.lower() or ".zip" in name:
                download_urls["windows_portable"] = url
            else:
                download_urls["windows"] = url
        elif ".deb" in name:
            download_urls["linux_deb"] = url
        elif ".tar.gz" in name or ".tgz" in name:
            download_urls["linux_tar"] = url

    release_notes = (data.get("body") or "")[:2000]

    result = {
        "update_available": latest_v > current_v if latest_v and current_v else False,
        "current_version": current_version,
        "latest_version": latest_tag,
        "release_url": data.get("html_url", ""),
        "release_notes": release_notes,
        "published_at": data.get("published_at", ""),
        "assets": assets,
        "download_urls": download_urls,
        "cached": False,
    }

    # 缓存
    _write_cache({
        "latest_version": latest_tag,
        "release_url": data.get("html_url", ""),
        "release_notes": release_notes,
        "published_at": data.get("published_at", ""),
        "assets": assets,
        "download_urls": download_urls,
    })

    return result


def clear_cache():
    """清除更新缓存"""
    try:
        UPDATE_CACHE_FILE.unlink(missing_ok=True)
    except Exception:
        pass
