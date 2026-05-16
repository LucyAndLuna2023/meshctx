"""
MeshCtx Auto-Update Checker
=============================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.
"""
import json
import urllib.request
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com/repos/LucyAndLuna2023/meshctx/releases/latest"
DOWNLOAD_URL = "https://github.com/LucyAndLuna2023/meshctx/releases/latest"


def check_update(current_version: str) -> Optional[Dict]:
    """Check GitHub for newer version."""
    try:
        req = urllib.request.Request(GITHUB_API, headers={
            "User-Agent": "MeshCtx/2.14",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        latest = data.get("tag_name", "").lstrip("v")
        if not latest:
            return None

        # Compare versions
        if _version_cmp(latest, current_version) > 0:
            return {
                "current": current_version,
                "latest": latest,
                "update_available": True,
                "download_url": DOWNLOAD_URL,
                "release_notes": data.get("body", "")[:500],
                "published_at": data.get("published_at", ""),
            }

        return {"current": current_version, "latest": latest, "update_available": False}

    except Exception as e:
        logger.warning(f"Update check failed: {e}")
        return None


def _version_cmp(a: str, b: str) -> int:
    """Compare two semver-like versions. Returns 1 if a > b, -1 if a < b, 0 if equal."""
    def parse(v):
        parts = []
        for p in v.replace("-", ".").split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(p)
        return parts

    al = parse(a)
    bl = parse(b)
    for i in range(max(len(al), len(bl))):
        av = al[i] if i < len(al) else 0
        bv = bl[i] if i < len(bl) else 0
        if isinstance(av, int) and isinstance(bv, int):
            if av > bv: return 1
            if av < bv: return -1
        else:
            sa, sb = str(av), str(bv)
            if sa > sb: return 1
            if sa < sb: return -1
    return 0
