"""
MeshCtx Skill Orchestrator — 技能编排引擎

基于用户意图自动发现、匹配和调用 Hermes 技能。
- IntentParser: 意图解析
- SkillMatcher: 技能匹配与排序
- Orchestrator: 编排执行

用法:
    from src.orchestrator import SkillOrchestrator
    orch = SkillOrchestrator()
    matches = orch.match("debug a python test failure")
    plan = orch.plan("add user authentication to my flask app")
"""

import re
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict

from .hermes_catalog import CapabilityCatalog, SkillEntry, get_catalog


# ═══════════════════════════════════════════════════════════════════════
# Intent Patterns — 意图模式匹配
# ═══════════════════════════════════════════════════════════════════════

INTENT_PATTERNS: list[tuple[str, list[str], str]] = [
    # (类别, 正则模式列表, 推荐主技能)
    ("debug", [
        r"\b(debug|fix|error|bug|crash|failed|broken|issue|not working)\b",
        r"\b(troubleshoot|diagnose|investigate)\b",
    ], "systematic-debugging"),
    ("test", [
        r"\b(test|pytest|unittest|coverage|TDD|tdd)\b",
        r"\b(write test|add test|test framework|testing setup)\b",
    ], "test-driven-development"),
    ("plan", [
        r"\b(plan|design|architecture|roadmap|proposal)\b",
        r"\b(how to|how should|what's the best way)\b",
    ], "writing-plans"),
    ("implement", [
        r"\b(implement|build|create|develop|code|write)\b.*\b(app|feature|endpoint|API|service|module)\b",
        r"\b(add|integrate|connect)\b.*\b(to|into|with)\b",
    ], "subagent-driven-development"),
    ("review", [
        r"\b(review|code review|PR review|check my code|audit)\b",
    ], "requesting-code-review"),
    ("research", [
        r"\b(research|paper|arxiv|study|literature|find papers)\b",
    ], "arxiv"),
    ("deploy", [
        r"\b(deploy|release|publish|CI|CD|pipeline)\b",
    ], "github-pr-workflow"),
    ("data", [
        r"\b(data|dataset|training|fine.?tun|ML|model train)\b",
    ], "axolotl"),
    ("diagram", [
        r"\b(diagram|chart|graph|visualiz|architecture (diagram|draw)|flowchart)\b",
    ], "architecture-diagram"),
    ("search", [
        r"\b(search|find|look up|google)\b",
    ], None),  # 使用原生 web_search 工具
    ("notify", [
        r"\b(notify|alert|monitor|watch|schedule|cron)\b",
    ], "cronjob"),
    ("docs", [
        r"\b(document|docstring|README|write doc|generate doc)\b",
    ], "writing-plans"),
    ("refactor", [
        r"\b(refactor|clean up|improve|optimize|rewrite)\b",
    ], "subagent-driven-development"),
    ("setup", [
        r"\b(setup|install|configure|init|bootstrap)\b",
    ], "python-test-framework-setup"),
    ("social", [
        r"\b(tweet|post to X|twitter|social media|publish)\b",
    ], "xurl"),
    ("email", [
        r"\b(email|send mail|inbox|smtp|imap)\b",
    ], "himalaya"),
    ("github", [
        r"\b(github|git commit|pull request|clone|fork|repo)\b",
    ], "github-pr-workflow"),
    ("mcp", [
        r"\b(MCP|model context protocol|mcp server)\b",
    ], "native-mcp"),
    ("music", [
        r"\b(music|song|audio|spotify|playlist|generate music)\b",
    ], "spotify"),
    ("note", [
        r"\b(note|obsidian|vault|knowledge base|second brain)\b",
    ], "obsidian"),
    ("infographic", [
        r"\b(infographic|信息图|data visual|chart|poster)\b",
    ], "baoyu-infographic"),
]


# ═══════════════════════════════════════════════════════════════════════
# Skill Chain Templates — 技能链（多技能编排）
# ═══════════════════════════════════════════════════════════════════════

SKILL_CHAINS: dict[str, list[str]] = {
    "feature-development": [
        "writing-plans",           # 1. 写计划
        "subagent-driven-development",  # 2. 分解执行
        "test-driven-development",      # 3. TDD 质量
        "requesting-code-review",       # 4. 审查
    ],
    "bug-fix": [
        "systematic-debugging",    # 1. 根因分析
        "test-driven-development",      # 2. 回归测试
    ],
    "code-review": [
        "requesting-code-review",  # 1. 安全+质量审查
        "github-code-review",           # 2. GitHub PR 审查
    ],
    "project-setup": [
        "python-test-framework-setup",  # 1. 测试框架
        "github-repo-management",       # 2. 仓库初始化
        "writing-plans",           # 3. 架构规划
    ],
    "ml-project": [
        "axolotl",                 # 1. 微调配置
        "huggingface-hub",         # 2. 模型仓库
        "evaluating-llms-harness", # 3. 评估
    ],
}


# ═══════════════════════════════════════════════════════════════════════
# Match Result
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class MatchResult:
    intent: str
    primary_skill: Optional[str]
    skills: list[tuple[SkillEntry, float]]
    skill_chain: Optional[list[str]]
    confidence: float

@dataclass
class ExecutionPlan:
    intent: str
    chain: list[str]
    steps: list[dict]


# ═══════════════════════════════════════════════════════════════════════
# Intent Parser
# ═══════════════════════════════════════════════════════════════════════

class IntentParser:
    """解析用户意图，匹配预定义模式。"""

    def parse(self, query: str) -> list[tuple[str, float]]:
        """返回 [(intent_category, confidence), ...]"""
        scores = defaultdict(float)
        query_lower = query.lower()

        for category, patterns, _ in INTENT_PATTERNS:
            for pat in patterns:
                if re.search(pat, query_lower):
                    scores[category] += 1.5
                # 部分匹配加分
                words = pat.replace(r"\b", "").split("|")
                for w in words:
                    w_clean = w.strip("()")
                    if w_clean and w_clean in query_lower:
                        scores[category] += 0.5

        # 归一化
        max_score = max(scores.values()) if scores else 1.0
        return sorted(
            [(cat, min(s / max_score, 1.0)) for cat, s in scores.items()],
            key=lambda x: x[1], reverse=True,
        )


# ═══════════════════════════════════════════════════════════════════════
# Skill Matcher
# ═══════════════════════════════════════════════════════════════════════

class SkillMatcher:
    """技能匹配器 — 综合意图+关键词+历史推荐。"""

    def __init__(self, catalog: Optional[CapabilityCatalog] = None):
        self.catalog = catalog or get_catalog()
        self.parser = IntentParser()

    def match(self, query: str) -> MatchResult:
        """匹配最佳技能组合。"""
        # 1. 意图解析
        intents = self.parser.parse(query)
        if not intents:
            return MatchResult("unknown", None, [], None, 0.0)

        primary_intent, intent_conf = intents[0]

        # 2. 技能搜索
        skills = self.catalog.find_skills(query, top_k=8)

        # 3. 确定主技能
        primary = None
        for cat, _, skill_name in INTENT_PATTERNS:
            if cat == primary_intent and skill_name:
                primary = skill_name
                break

        # 如果意图匹配不到主技能，取技能搜索结果第一
        if not primary and skills:
            primary = skills[0][0].name

        # 4. 技能链
        chain = SKILL_CHAINS.get(primary_intent)

        # 5. 综合置信度
        skill_conf = skills[0][1] / 10.0 if skills else 0.0
        confidence = min(intent_conf * 0.6 + skill_conf * 0.4, 1.0)

        return MatchResult(
            intent=primary_intent,
            primary_skill=primary,
            skills=skills,
            skill_chain=chain,
            confidence=confidence,
        )

    def get_chain(self, chain_name: str) -> Optional[list[str]]:
        return SKILL_CHAINS.get(chain_name)


# ═══════════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════════

class SkillOrchestrator:
    """技能编排器 — 高层入口。"""

    def __init__(self, catalog: Optional[CapabilityCatalog] = None):
        self.catalog = catalog or get_catalog()
        self.matcher = SkillMatcher(self.catalog)

    def match(self, query: str) -> MatchResult:
        """匹配用户意图 → 推荐技能。"""
        return self.matcher.match(query)

    def plan(self, query: str) -> ExecutionPlan:
        """生成执行计划。"""
        result = self.matcher.match(query)

        steps = []
        # 如果有技能链，拆解为步骤
        if result.skill_chain:
            for i, skill_name in enumerate(result.skill_chain):
                skill = self.catalog.skill_info(skill_name)
                steps.append({
                    "step": i + 1,
                    "skill": skill_name,
                    "description": skill.description if skill else "",
                    "category": skill.category if skill else "",
                })
        elif result.primary_skill:
            skill = self.catalog.skill_info(result.primary_skill)
            steps.append({
                "step": 1,
                "skill": result.primary_skill,
                "description": skill.description if skill else "",
                "category": skill.category if skill else "",
            })

        return ExecutionPlan(
            intent=result.intent,
            chain=result.skill_chain or [],
            steps=steps,
        )

    def get_recommended_skills(self, query: str, top_k: int = 5) -> list[dict]:
        """获取推荐技能列表。"""
        result = self.matcher.match(query)
        return [
            {
                "name": skill.name,
                "category": skill.category,
                "description": skill.description,
                "score": round(score, 2),
                "tags": skill.tags,
            }
            for skill, score in result.skills[:top_k]
        ]


# 全局单例
_orchestrator: Optional[SkillOrchestrator] = None

def get_orchestrator() -> SkillOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = SkillOrchestrator()
    return _orchestrator
