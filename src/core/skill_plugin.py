"""
meshctx v3.84 — Skill Plugin System (技能插件系统)

核心功能:
  1. SKILL.md 解析器 — 读取 YAML frontmatter + markdown body
  2. Skill 注册中心 — 从 skills/ 目录自动发现和加载
  3. Skill 调用 — 根据触发条件匹配 → 注入上下文 → 返回激活的 Skill
  4. 热更新 — 检测文件变化自动重载 (mtime polling)

SKILL.md 格式 (guizang 兼容):
  ---
  name: skill-name
  description: What this skill does
  triggers:
    - keyword or phrase
    - another trigger
  tools:
    - tool_a
    - tool_b
  ---
  # Body (markdown)

用法:
    mgr = SkillPluginManager(skills_dir="skills/")
    mgr.discover()                    # 扫描并加载所有 SKILL.md
    matched = mgr.match("user query") # 按触发条件匹配
    context = mgr.inject(skill, {})   # 生成注入用的上下文
    mgr.reload()                      # 检查文件变化并热重载
"""

import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.skill_plugin")


# ── Exceptions ─────────────────────────────────────────────────────

class SkillPluginError(Exception):
    """Skill 插件系统异常基类"""


class SkillParseError(SkillPluginError):
    """SKILL.md 解析错误"""


class SkillNotFoundError(SkillPluginError):
    """Skill 未找到"""


# ── Data Classes ───────────────────────────────────────────────────

@dataclass
class SkillPlugin:
    """解析后的 Skill 实体"""
    name: str
    description: str = ""
    triggers: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    body: str = ""                          # markdown body (不含 frontmatter)
    raw_frontmatter: Dict[str, Any] = field(default_factory=dict)
    file_path: str = ""                     # SKILL.md 绝对路径
    mtime: float = 0.0                      # 文件修改时间 (用于热更新)
    version: str = "1.0.0"
    category: str = "general"
    priority: int = 0
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "triggers": self.triggers,
            "tools": self.tools,
            "body": self.body,
            "raw_frontmatter": self.raw_frontmatter,
            "file_path": self.file_path,
            "version": self.version,
            "category": self.category,
            "priority": self.priority,
            "enabled": self.enabled,
        }

    @property
    def skill_dir(self) -> str:
        """返回 SKILL.md 所在目录"""
        return str(Path(self.file_path).parent) if self.file_path else ""

    @property
    def full_context(self) -> str:
        """返回完整的上下文文本 (body 即 markdown)"""
        return self.body


# ── Main Manager ───────────────────────────────────────────────────

class SkillPluginManager:
    """
    Skill 插件管理器 — v3.84

    管理 SKILL.md 插件的发现、加载、匹配和热更新。

    用法:
        mgr = SkillPluginManager(skills_dir="skills/")
        mgr.discover()
        # 查找匹配的 Skill
        matched = mgr.match("I need to create a FastAPI endpoint")
        if matched:
            context = mgr.inject(matched[0], {"task": "create API"})
    """

    def __init__(self, skills_dir: str = "skills/"):
        self.skills_dir = Path(skills_dir)
        # 注册表: name → SkillPlugin
        self._registry: Dict[str, SkillPlugin] = {}
        # 文件路径 → mtime (用于热更新检测)
        self._file_mtimes: Dict[str, float] = {}
        # 统计
        self._discover_count: int = 0
        self._reload_count: int = 0
        self._match_count: int = 0

    # ── Discovery ──────────────────────────────────────────────────

    def discover(self, skills_dir: Optional[str] = None) -> int:
        """
        扫描 skills/ 目录，递归发现所有 SKILL.md 文件并加载。

        Args:
            skills_dir: 可选，覆盖默认目录

        Returns:
            int: 新加载的 Skill 数量
        """
        if skills_dir:
            self.skills_dir = Path(skills_dir)

        scan_dir = self.skills_dir.resolve()
        if not scan_dir.exists():
            logger.warning(f"Skills 目录不存在: {scan_dir}，跳过发现")
            return 0

        loaded = 0
        for skill_file in scan_dir.rglob("SKILL.md"):
            try:
                skill = self._parse_skill_md(skill_file)
                if skill and skill.enabled:
                    self._registry[skill.name] = skill
                    self._file_mtimes[str(skill_file)] = skill.mtime
                    loaded += 1
                    logger.debug(f"Skill 已加载: {skill.name} ← {skill_file}")
            except SkillParseError as e:
                logger.warning(f"SKILL.md 解析失败 {skill_file}: {e}")
            except Exception as e:
                logger.error(f"加载 Skill 失败 {skill_file}: {e}")

        self._discover_count += 1
        logger.info(f"Skill 发现完成: {loaded} 个技能已加载 (目录: {scan_dir})")
        return loaded

    def reload(self) -> Dict[str, List[str]]:
        """
        热重载：检测文件变化并重新加载。

        基于文件 mtime 检测变更：
        - 新增文件 → 加载
        - 修改文件 → 重新加载
        - 删除文件 → 从注册表移除

        Returns:
            Dict[str, List[str]]: {"added": [...], "updated": [...], "removed": [...]}
        """
        changes: Dict[str, List[str]] = {"added": [], "updated": [], "removed": []}

        scan_dir = self.skills_dir.resolve()
        if not scan_dir.exists():
            return {k: v for k, v in changes.items()}

        # 扫描当前磁盘上的所有 SKILL.md
        current_files: Dict[str, float] = {}
        for skill_file in scan_dir.rglob("SKILL.md"):
            current_files[str(skill_file)] = skill_file.stat().st_mtime

        known_paths = set(self._file_mtimes.keys())
        current_paths = set(current_files.keys())

        # 新增: 在磁盘上但不在注册表中
        for path_str in current_paths - known_paths:
            try:
                skill = self._parse_skill_md(Path(path_str))
                if skill and skill.enabled:
                    self._registry[skill.name] = skill
                    self._file_mtimes[path_str] = current_files[path_str]
                    changes["added"].append(skill.name)
                    logger.info(f"Skill 新增 (热更新): {skill.name}")
            except Exception as e:
                logger.warning(f"热更新加载失败 {path_str}: {e}")

        # 删除: 在注册表中但不在磁盘上
        for path_str in known_paths - current_paths:
            old_mtime = self._file_mtimes.pop(path_str, 0)
            # 找到并移除对应 Skill
            for name, skill in list(self._registry.items()):
                if skill.file_path == path_str:
                    del self._registry[name]
                    changes["removed"].append(name)
                    logger.info(f"Skill 已移除 (文件删除): {name}")
                    break

        # 修改: 在两边都存在但 mtime 不同
        for path_str in known_paths & current_paths:
            disk_mtime = current_files[path_str]
            cached_mtime = self._file_mtimes.get(path_str, 0)
            if abs(disk_mtime - cached_mtime) > 0.001:
                try:
                    skill = self._parse_skill_md(Path(path_str))
                    if skill and skill.enabled:
                        self._registry[skill.name] = skill
                        self._file_mtimes[path_str] = disk_mtime
                        changes["updated"].append(skill.name)
                        logger.info(f"Skill 已更新 (热重载): {skill.name}")
                except Exception as e:
                    logger.warning(f"热重载解析失败 {path_str}: {e}")

        self._reload_count += 1
        total = sum(len(v) for v in changes.values())
        if total:
            logger.info(
                f"热重载完成: +{len(changes['added'])}新 "
                f"~{len(changes['updated'])}改 "
                f"-{len(changes['removed'])}删"
            )
        return {k: v for k, v in changes.items()}

    # ── Parsing ────────────────────────────────────────────────────

    def _parse_skill_md(self, file_path: Path) -> Optional[SkillPlugin]:
        """
        解析单个 SKILL.md 文件。

        SKILL.md 格式:
          ---
          name: my-skill
          description: ...
          triggers: [...]
          tools: [...]
          ---
          # Markdown Body

        Args:
            file_path: SKILL.md 文件路径

        Returns:
            SkillPlugin 或 None (解析失败时)

        Raises:
            SkillParseError: frontmatter 格式错误
        """
        if not file_path.exists():
            raise SkillParseError(f"文件不存在: {file_path}")

        content = file_path.read_text(encoding="utf-8")
        mtime = file_path.stat().st_mtime

        frontmatter, body = self._split_frontmatter(content, str(file_path))
        if not frontmatter and not body:
            raise SkillParseError(f"空的 SKILL.md: {file_path}")

        # 解析 frontmatter (支持 YAML 和 simplified colon 格式)
        data: Dict[str, Any] = {}
        if frontmatter:
            data = self._parse_frontmatter_data(frontmatter)

        name = data.get("name", file_path.parent.name)
        description = data.get("description", "")
        triggers = self._normalize_list(data.get("triggers", []))
        tools = self._normalize_list(data.get("tools", []))
        version = str(data.get("version", "1.0.0"))
        category = data.get("category", "general")
        priority = int(data.get("priority", 0))
        enabled = data.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.lower() in ("true", "1", "yes")

        return SkillPlugin(
            name=name,
            description=description,
            triggers=triggers,
            tools=tools,
            body=body.strip(),
            raw_frontmatter=data,
            file_path=str(file_path.resolve()),
            mtime=mtime,
            version=version,
            category=category,
            priority=priority,
            enabled=enabled,
        )

    @staticmethod
    def _split_frontmatter(content: str, source: str = "") -> Tuple[str, str]:
        """
        分割 YAML frontmatter 和 markdown body。

        Frontmatter 以 --- 开头和结尾。
        """
        content = content.lstrip("\ufeff")  # strip BOM
        # 必须以 --- 开头
        if not content.startswith("---"):
            return "", content

        # 找到第二个 ---
        end_idx = content.find("---", 3)
        if end_idx == -1:
            # 只有一个 ---，可能整个文件就是 frontmatter
            return content[3:].strip(), ""

        frontmatter = content[3:end_idx].strip()
        body = content[end_idx + 3:].strip()
        return frontmatter, body

    @staticmethod
    def _parse_frontmatter_data(frontmatter: str) -> Dict[str, Any]:
        """
        解析 frontmatter 数据 (YAML优先 → 简化格式回退)。
        """
        # 尝试 YAML
        yaml_mod = None
        try:
            import yaml as _ym
            yaml_mod = _ym  # type: ignore[assignment]
        except ImportError:
            pass

        if yaml_mod is not None:
            try:
                return yaml_mod.safe_load(frontmatter) or {}  # type: ignore[union-attr]
            except Exception:
                pass  # 回退到简化格式

        # 简化格式回退
        return SkillPluginManager._parse_simple_frontmatter(frontmatter)

    @staticmethod
    def _parse_simple_frontmatter(frontmatter: str) -> Dict[str, Any]:
        """
        简化 frontmatter 解析 (无 YAML 库时回退)。

        支持格式:
          key: value
          key:
            - item1
            - item2
        """
        data: Dict[str, Any] = {}
        current_key = None
        current_list: List[str] = []

        for line in frontmatter.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # 检测列表项
            if stripped.startswith("- "):
                item = stripped[2:].strip().strip("'\"")
                if current_key:
                    current_list.append(item)
                continue

            # 保存之前的列表
            if current_key and current_list:
                data[current_key] = current_list
                current_list = []

            # 解析 key: value
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip().strip("'\"")
                if value == "":
                    current_key = key
                    current_list = []
                else:
                    data[key] = value
                    current_key = None
            else:
                current_key = None

        # 清理结尾
        if current_key and current_list:
            data[current_key] = current_list

        return data

    @staticmethod
    def _normalize_list(value: Any) -> List[str]:
        """标准化为字符串列表"""
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            return [value] if value else []
        return []

    # ── Matching ───────────────────────────────────────────────────

    def match(
        self, query: str, *, threshold: float = 0.0, limit: int = 10,
    ) -> List[SkillPlugin]:
        """
        根据触发条件匹配 Skill。

        匹配策略：
        1. 精确关键词匹配 (query 中包含 trigger 字符串)
        2. 模糊子串匹配 (不区分大小写)
        3. 正则匹配 (trigger 以 /regex/ 包裹时)
        4. 按 priority 降序 + 匹配度排序

        Args:
            query: 用户输入或任务描述
            threshold: 最低匹配分数 (0=任意匹配, >0=过滤低分匹配)
            limit: 最多返回 N 个结果

        Returns:
            List[SkillPlugin]: 匹配的 Skill 列表 (按匹配度降序)
        """
        query_lower = query.lower()
        scored: List[Tuple[SkillPlugin, float]] = []

        for skill in self._registry.values():
            if not skill.enabled:
                continue

            score = self._compute_match_score(skill, query, query_lower)
            if score > threshold:
                scored.append((skill, score))

        # 排序: 先按 priority 降序，再按 match score 降序
        scored.sort(key=lambda x: (x[0].priority, x[1]), reverse=True)

        self._match_count += 1
        return [s for s, _ in scored[:limit]]

    def _compute_match_score(
        self, skill: SkillPlugin, query: str, query_lower: str,
    ) -> float:
        """计算 Skill 对 query 的匹配分数。"""
        if not skill.triggers:
            return 0.0

        best_score = 0.0

        for trigger in skill.triggers:
            trigger_lower = trigger.lower()

            # 正则模式: /pattern/flags
            if trigger.startswith("/") and trigger.endswith("/") and len(trigger) >= 3:
                try:
                    pattern = trigger[1:-1]
                    if re.search(pattern, query, re.IGNORECASE):
                        best_score = max(best_score, 2.0)
                        break
                except re.error:
                    pass
                continue

            # 精确子串匹配
            if trigger_lower in query_lower:
                # 长度比分: 越长越精确
                ratio = len(trigger) / max(len(query), 1)
                score = 1.0 + ratio
                best_score = max(best_score, score)

            # 分词匹配 (trigger 中每个词都在 query 中出现)
            elif len(trigger_lower.split()) > 1:
                tokens = trigger_lower.split()
                if all(tok in query_lower for tok in tokens):
                    score = 0.5 + (len(tokens) / max(len(query_lower.split()), 1))
                    best_score = max(best_score, score)

        # 额外加分: 描述中关键词匹配
        if skill.description:
            desc_lower = skill.description.lower()
            desc_words = set(desc_lower.split())
            query_words = set(query_lower.split())
            overlap = desc_words & query_words
            if overlap:
                best_score += 0.1 * min(len(overlap), 5)

        return round(best_score, 3)

    # ── Context Injection ──────────────────────────────────────────

    def inject(self, skill: SkillPlugin, context: Optional[Dict[str, Any]] = None) -> str:
        """
        将 Skill 上下文注入到提示中。

        生成格式:
          [Skill: {name}]
          {description}
          ---
          {markdown body}

        Args:
            skill: 目标 Skill
            context: 额外上下文变量 (用于模板替换)

        Returns:
            str: 注入后的完整上下文文本
        """
        context = context or {}

        # 简单模板替换: {key} → value
        body = skill.body
        for key, value in context.items():
            body = body.replace(f"{{{key}}}", str(value))

        parts = [f"[Skill: {skill.name}]"]
        if skill.description:
            parts.append(skill.description)
        parts.append("---")
        parts.append(body)

        return "\n".join(parts)

    def inject_all(
        self, skills: List[SkillPlugin], context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        注入多个 Skill 的上下文，用分隔符隔开。

        Args:
            skills: Skill 列表
            context: 共享上下文变量

        Returns:
            str: 合并后的上下文
        """
        parts = []
        for i, skill in enumerate(skills):
            parts.append(self.inject(skill, context))
            if i < len(skills) - 1:
                parts.append("\n===\n")
        return "\n".join(parts)

    # ── Accessors ──────────────────────────────────────────────────

    def get(self, name: str) -> Optional[SkillPlugin]:
        """按名称获取 Skill"""
        return self._registry.get(name)

    def get_all(self) -> List[SkillPlugin]:
        """获取所有已注册的 Skill"""
        return list(self._registry.values())

    def get_by_category(self, category: str) -> List[SkillPlugin]:
        """按类别获取 Skill 列表"""
        return [s for s in self._registry.values() if s.category == category]

    def list_names(self) -> List[str]:
        """列出所有 Skill 名称"""
        return sorted(self._registry.keys())

    def __len__(self) -> int:
        return len(self._registry)

    def __contains__(self, name: str) -> bool:
        return name in self._registry

    def __iter__(self):
        return iter(self._registry.values())

    def __repr__(self) -> str:
        return (
            f"SkillPluginManager(n={len(self._registry)}, "
            f"dir={self.skills_dir}, "
            f"discovers={self._discover_count}, "
            f"reloads={self._reload_count})"
        )

    # ── Stats ──────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """返回统计信息"""
        skills = self.get_all()
        categories = {}
        for s in skills:
            categories[s.category] = categories.get(s.category, 0) + 1
        return {
            "total_skills": len(skills),
            "enabled": sum(1 for s in skills if s.enabled),
            "disabled": sum(1 for s in skills if not s.enabled),
            "categories": categories,
            "total_triggers": sum(len(s.triggers) for s in skills),
            "total_tools": sum(len(s.tools) for s in skills),
            "discover_count": self._discover_count,
            "reload_count": self._reload_count,
            "match_count": self._match_count,
            "skills_dir": str(self.skills_dir),
        }

    # ── Management ─────────────────────────────────────────────────

    def register(self, skill: SkillPlugin) -> None:
        """手动注册一个 Skill (不写文件)"""
        self._registry[skill.name] = skill
        if skill.file_path:
            self._file_mtimes[skill.file_path] = skill.mtime
        logger.debug(f"Skill 手动注册: {skill.name}")

    def unregister(self, name: str) -> bool:
        """按名称注销 Skill"""
        skill = self._registry.pop(name, None)
        if skill and skill.file_path:
            self._file_mtimes.pop(skill.file_path, None)
        if skill:
            logger.debug(f"Skill 已注销: {name}")
            return True
        return False

    def enable(self, name: str) -> bool:
        """启用 Skill"""
        skill = self._registry.get(name)
        if skill:
            skill.enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """禁用 Skill (保留在注册表中)"""
        skill = self._registry.get(name)
        if skill:
            skill.enabled = False
            return True
        return False

    def clear(self) -> None:
        """清空注册表"""
        self._registry.clear()
        self._file_mtimes.clear()
        logger.debug("Skill 注册表已清空")


# ── Module-level convenience ───────────────────────────────────────

_INSTANCE: Optional[SkillPluginManager] = None


def get_skill_plugin_manager(skills_dir: str = "skills/") -> SkillPluginManager:
    """获取全局 SkillPluginManager 单例"""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SkillPluginManager(skills_dir=skills_dir)
    return _INSTANCE


def reset_skill_plugin_manager() -> None:
    """重置全局单例"""
    global _INSTANCE
    if _INSTANCE:
        _INSTANCE.clear()
    _INSTANCE = None
