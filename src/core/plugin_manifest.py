"""
MeshCtx v2.0 — 插件清单标准 (Plugin Manifest Standard)
PRD §5.1 — 统一插件生态
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class PluginManifest:
    """插件清单 — 跨平台统一描述"""
    name: str
    version: str
    api_version: str = "meshctx@2.0"
    description: str = ""
    author: str = ""
    permissions: List[str] = field(default_factory=list)
    platforms: List[str] = field(default_factory=lambda: ["windows", "macos", "linux"])
    platform_overrides: Dict[str, Dict] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    entry_point: str = ""
    min_meshctx_version: str = "1.9.0"

    @classmethod
    def from_dict(cls, data: Dict) -> "PluginManifest":
        return cls(**{k: v for k, v in data.items()
                     if k in cls.__dataclass_fields__})

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "version": self.version,
            "apiVersion": self.api_version,
            "description": self.description,
            "author": self.author,
            "permissions": self.permissions,
            "platforms": self.platforms,
            "platformOverrides": self.platform_overrides,
            "dependencies": self.dependencies,
            "entryPoint": self.entry_point,
            "minMeshctxVersion": self.min_meshctx_version,
        }

    def validate(self) -> List[str]:
        """验证清单合法性，返回错误列表"""
        errors = []
        if not self.name or len(self.name) < 3:
            errors.append("name 必须至少3个字符")
        if not self.version:
            errors.append("version 不能为空")
        if not self.entry_point:
            errors.append("entry_point 不能为空")
        
        # 权限白名单
        valid_perms = {"network:search", "network:api", "fs:read", "fs:write",
                      "exec:shell", "exec:python", "memory:access", "model:call"}
        for p in self.permissions:
            if p not in valid_perms:
                errors.append(f"未知权限: {p}")
        
        valid_platforms = {"windows", "macos", "linux", "web", "android", "ios"}
        for p in self.platforms:
            if p not in valid_platforms:
                errors.append(f"未知平台: {p}")
        
        return errors

    def is_compatible_with(self, platform: str) -> bool:
        """检查是否兼容指定平台"""
        return platform in self.platforms

    def get_platform_deps(self, platform: str) -> List[str]:
        """获取平台特定依赖"""
        return self.platform_overrides.get(platform, {}).get("dependencies", [])


# 示例清单
EXAMPLE_MANIFEST = PluginManifest(
    name="web-search-tool",
    version="1.0.0",
    description="Web搜索工具插件，支持多搜索引擎",
    author="MeshCtx Community",
    permissions=["network:search", "fs:read"],
    platforms=["windows", "macos", "linux"],
    platform_overrides={
        "windows": {"dependencies": ["winhttp.dll"]},
        "linux": {"dependencies": ["libcurl.so.4"]},
    },
    entry_point="web_search.manifest",
)

EXAMPLE_JSON = json.dumps(EXAMPLE_MANIFEST.to_dict(), indent=2, ensure_ascii=False)
