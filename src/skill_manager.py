"""
meshctx Skill 管理系统
- 创建 / 加载 / 自动发现
- 元认知驱动的自动 Skill 生成
- Skill 版本管理
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("meshctx.skill")


@dataclass
class Skill:
    """Skill 定义"""
    name: str
    description: str
    version: str = "1.0.0"
    trigger: str = ""              # 触发条件描述
    steps: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    model: str = "bailian-free"
    created_at: str = ""
    updated_at: str = ""
    usage_count: int = 0
    success_rate: float = 0.0
    source: str = "manual"         # manual|auto|imported

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "trigger": self.trigger,
            "steps": self.steps,
            "tools": self.tools,
            "model": self.model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Skill":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SkillManager:
    """
    Skill 管理器
    
    用法:
        mgr = SkillManager(skill_dir)
        mgr.create("web-search", "搜索网页", steps=[...])
        mgr.list()
        mgr.load("web-search")
    """

    def __init__(self, skill_dir: str = "~/.meshctx/skills/"):
        self.skill_dir = Path(skill_dir).expanduser().resolve()
        self.skill_dir.mkdir(parents=True, exist_ok=True)
        self._loaded: Dict[str, Skill] = {}
        self._discover()

    def _discover(self):
        """从磁盘发现所有 Skill"""
        for file in self.skill_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                skill = Skill.from_dict(data)
                self._loaded[skill.name] = skill
            except Exception as e:
                logger.warning(f"跳过无效 Skill 文件 {file.name}: {e}")
        logger.info(f"发现 {len(self._loaded)} 个 Skill")

    # ── CRUD ──────────────────────────────────────────

    def create(self, name: str, description: str, **kwargs) -> Skill:
        """创建新 Skill"""
        now = datetime.now().isoformat()
        skill = Skill(
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
            **kwargs,
        )
        self._loaded[name] = skill
        self._save(skill)
        logger.info(f"Skill 已创建: {name}")
        return skill

    def get(self, name: str) -> Optional[Skill]:
        return self._loaded.get(name)

    def list_all(self) -> List[Skill]:
        return list(self._loaded.values())

    def delete(self, name: str) -> bool:
        if name not in self._loaded:
            return False
        del self._loaded[name]
        file = self.skill_dir / f"{name}.json"
        if file.exists():
            file.unlink()
        return True

    def _save(self, skill: Skill):
        """持久化到磁盘"""
        file = self.skill_dir / f"{skill.name}.json"
        with open(file, "w", encoding="utf-8") as f:
            json.dump(skill.to_dict(), f, ensure_ascii=False, indent=2)

    # ── 自动创建 ──────────────────────────────────────

    def auto_create_from_pattern(self, pattern: Dict, model_adapter=None) -> Optional[Skill]:
        """
        从成功任务模式自动生成 Skill
        由元认知引擎驱动
        """
        name = pattern.get("task_pattern", "auto-skill")[:50]
        name = name.lower().replace(" ", "-").replace("_", "-")
        name = "".join(c for c in name if c.isalnum() or c == "-")[:40]

        # 如果已有同名 Skill，更新
        existing = self._loaded.get(name)
        if existing:
            existing.usage_count += 1
            existing.updated_at = datetime.now().isoformat()
            existing.success_rate = pattern.get("avg_quality", 0.5)
            self._save(existing)
            return existing

        if model_adapter and model_adapter.is_ready:
            skill_def = model_adapter.generate_skill(pattern)
            if skill_def:
                return self.create(
                    name=skill_def.get("name", name),
                    description=skill_def.get("description", ""),
                    trigger=skill_def.get("trigger", ""),
                    steps=skill_def.get("steps", []),
                    tools=skill_def.get("tools", []),
                    model=skill_def.get("model", "bailian-free"),
                    source="auto",
                )

        # 回退：基于模式创建
        return self.create(
            name=name,
            description=pattern.get("task_pattern", "")[:100],
            trigger=f"任务描述包含: {pattern.get('task_pattern','')[:50]}",
            steps=["执行任务", "验证结果"],
            tools=pattern.get("common_tools", []),
            source="auto",
        )

    # ── 统计 ──────────────────────────────────────────

    def stats(self) -> Dict:
        skills = self.list_all()
        return {
            "total": len(skills),
            "auto_created": sum(1 for s in skills if s.source == "auto"),
            "manual": sum(1 for s in skills if s.source == "manual"),
            "total_usage": sum(s.usage_count for s in skills),
            "top_skills": sorted(
                [{"name": s.name, "usage": s.usage_count, "success": s.success_rate}
                 for s in skills],
                key=lambda x: x["usage"], reverse=True
            )[:5],
        }
