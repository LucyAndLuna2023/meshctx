"""
MeshCtx Adapter — Hermes 上下文适配器

桥接 meshctx 的 MemoryEngine 与 Hermes 的 memory / session_search 工具，
实现双向上下文同步。

核心功能:
- 将 meshctx 存储的消息同步到 Hermes memory（持久化偏好/事实）
- 从 Hermes session_search 拉取历史会话上下文
- 提供统一的 ContextPortal API
"""

import json
from typing import Optional
from datetime import datetime, timezone

from .memory_engine import MemoryEngine, get_engine
from .capabilities import CapabilityCatalog, SkillEntry, get_catalog


# ═══════════════════════════════════════════════════════════════════════
# Context Portal — 统一上下文入口
# ═══════════════════════════════════════════════════════════════════════

class ContextPortal:
    """
    meshctx ↔ Hermes 双向上下文桥接器。

    用法:
        portal = ContextPortal()
        portal.sync_to_hermes_memory("myapp", "用户偏好 Python")
        context = portal.get_full_context("myapp")
    """

    def __init__(
        self,
        engine: Optional[MemoryEngine] = None,
        catalog: Optional[CapabilityCatalog] = None,
    ):
        self.engine = engine or get_engine()
        self.catalog = catalog or get_catalog()

    # ── 向 Hermes memory 同步 ─────────────────────────────────────

    def sync_to_hermes_memory(self, project_id: str, limit: int = 20) -> dict:
        """
        将 meshctx 中的重要事实同步到 Hermes memory。

        从 meshctx 的 facts 表中提取高置信度事实，
        格式化为 Hermes memory tool 可消费的格式。
        """
        facts = self.engine.cross_platform_engine.get_facts(project_id, limit=limit)
        high_conf = [f for f in facts if f.get("confidence", 1.0) >= 0.7]

        memory_entries = []
        for f in high_conf:
            entry = {
                "content": f["fact"],
                "source": "meshctx",
                "project_id": project_id,
                "timestamp": f.get("created_at", datetime.now(timezone.utc).isoformat()),
            }
            memory_entries.append(entry)

        return {
            "project_id": project_id,
            "synced_count": len(memory_entries),
            "entries": memory_entries,
            "_hermes_memory_hint": (
                "Use the memory tool with action='add', target='memory' "
                "to persist these entries into Hermes's durable memory."
            ),
        }

    def extract_context_for_hermes(self, project_id: str, max_tokens: int = 2000) -> str:
        """
        提取项目上下文，格式化为 Hermes 可注入的文本块。

        用于在新建会话时，将该上下文注入到 Hermes 的 system prompt。
        """
        ctx = self.engine.get_context(project_id, limit=30)
        facts = self.engine.cross_platform_engine.get_facts(project_id, limit=30)

        parts = [f"## MeshCtx Project Context: {project_id}\n"]

        if facts:
            parts.append("### Key Facts")
            for f in facts:
                parts.append(f"- {f['fact']}")

        if ctx["recent_messages"]:
            parts.append("\n### Recent Messages")
            for m in ctx["recent_messages"][-10:]:  # 最近 10 条
                role = m.get("role", "user")
                content = m.get("content", "")
                if len(content) > 200:
                    content = content[:200] + "..."
                parts.append(f"[{role}] {content}")

        result = "\n".join(parts)
        if len(result) > max_tokens * 4:  # 粗略估算
            result = result[:max_tokens * 4] + "\n[...truncated]"
        return result

    # ── 从 Hermes 拉取上下文 ──────────────────────────────────────

    def import_from_session_search(self, query: str, project_id: str = "default") -> dict:
        """
        生成一个供 Hermes session_search 工具使用的查询参数。
        meshctx 本身不调用 session_search（那是 Hermes 的工具），
        但提供格式化的查询建议。
        """
        return {
            "action": "search",
            "tool": "session_search",
            "query": query,
            "project_id": project_id,
            "hint": (
                "Use session_search tool with this query to find relevant "
                "past conversations, then call meshctx's add_message to "
                "import the context."
            ),
        }

    # ── 统一上下文 ───────────────────────────────────────────────

    def get_full_context(self, project_id: str) -> dict:
        """获取完整上下文（meshctx 内部 + Hermes 同步建议）。"""
        meshctx_ctx = self.engine.get_context(project_id)
        sync_data = self.sync_to_hermes_memory(project_id)

        return {
            "project_id": project_id,
            "meshctx_context": {
                "message_count": meshctx_ctx["message_count"],
                "recent_messages": meshctx_ctx["recent_messages"],
                "extracted_facts": meshctx_ctx["extracted_facts"],
            },
            "hermes_sync": {
                "pending_memory_entries": sync_data["synced_count"],
                "entries": sync_data["entries"],
            },
            "capabilities_snapshot": self.catalog.stats(),
        }

    # ── 技能上下文 ───────────────────────────────────────────────

    def get_skill_context(self, query: str) -> dict:
        """获取与查询相关的 Hermes 技能上下文。"""
        from .orchestrator import get_orchestrator
        orch = get_orchestrator()
        matches = orch.get_recommended_skills(query)
        return {
            "query": query,
            "recommended_skills": matches,
            "hint": (
                "Use skill_view tool to load skill details, "
                "then follow its instructions."
            ),
        }

    def get_plan_context(self, query: str) -> dict:
        """获取执行计划上下文。"""
        from .orchestrator import get_orchestrator
        orch = get_orchestrator()
        plan = orch.plan(query)
        return {
            "query": query,
            "intent": plan.intent,
            "skill_chain": plan.chain,
            "steps": plan.steps,
        }


# ═══════════════════════════════════════════════════════════════════════
# Skill Context Provider — 为技能提供上下文
# ═══════════════════════════════════════════════════════════════════════

class SkillContextProvider:
    """
    为 Hermes 技能加载提供智能上下文注入。

    当 AI 要加载某个技能时，自动注入：
    - meshctx 中相关的历史上下文
    - 之前使用该技能的经验教训
    - 相关的环境变量和依赖检查
    """

    def __init__(self, portal: Optional[ContextPortal] = None):
        self.portal = portal or ContextPortal()
        self.skill_history: dict[str, list[dict]] = {}

    def prepare_skill_context(
        self, skill_name: str, project_id: str = "default"
    ) -> dict:
        """为加载技能准备上下文。"""
        skill = self.catalog.skill_info(skill_name)

        result = {
            "skill": skill_name,
            "skill_info": {
                "description": skill.description if skill else "",
                "category": skill.category if skill else "",
                "tags": skill.tags if skill else [],
                "related_skills": skill.related if skill else [],
            },
            "project_context": self.portal.extract_context_for_hermes(project_id),
            "usage_history": self.skill_history.get(skill_name, []),
            "checks": {
                "requires_env": skill.requires_env if skill else [],
                "requires_commands": skill.requires_commands if skill else [],
            },
        }

        # 记录使用
        self.skill_history.setdefault(skill_name, []).append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
        })

        return result

    @property
    def catalog(self):
        return get_catalog()


# 全局单例
_portal: Optional[ContextPortal] = None

def get_portal() -> ContextPortal:
    global _portal
    if _portal is None:
        _portal = ContextPortal()
    return _portal
