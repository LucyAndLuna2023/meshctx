"""Goal Decomposer — v2.67
━━━━━━━━━━━━━━━━━━━━━━━━
输入高层目标 → 输出可执行子任务DAG

解决: "AI agent can't handle complex multi-step tasks"
"""
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    READY = "ready"      # 依赖已满足
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"  # 依赖失败


@dataclass
class SubTask:
    """子任务"""
    id: str
    description: str
    dependencies: List[str] = field(default_factory=list)
    estimated_minutes: float = 5.0
    priority: int = 0          # 0=normal, 1=high, 2=critical
    category: str = "general"
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None


@dataclass
class Goal:
    """目标"""
    id: str
    description: str
    subtasks: List[SubTask] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    deadline: Optional[float] = None
    progress: float = 0.0       # 0.0-1.0


class GoalDecomposer:
    """目标分解器"""

    # 常见目标模板
    _TEMPLATES: Dict[str, List[Dict]] = {
        "build_web_app": [
            {"desc": "设计数据库模型", "deps": [], "cat": "design", "est": 15},
            {"desc": "搭建项目框架", "deps": [], "cat": "setup", "est": 10},
            {"desc": "实现API端点", "deps": ["设计数据库模型"], "cat": "backend", "est": 30},
            {"desc": "实现前端页面", "deps": ["搭建项目框架"], "cat": "frontend", "est": 40},
            {"desc": "编写测试用例", "deps": ["实现API端点"], "cat": "test", "est": 20},
            {"desc": "部署上线", "deps": ["编写测试用例", "实现前端页面"], "cat": "deploy", "est": 15},
        ],
        "fix_bug": [
            {"desc": "复现Bug并记录", "deps": [], "cat": "debug", "est": 10},
            {"desc": "定位根因", "deps": ["复现Bug并记录"], "cat": "debug", "est": 15},
            {"desc": "编写回归测试", "deps": ["定位根因"], "cat": "test", "est": 10},
            {"desc": "实施修复", "deps": ["编写回归测试"], "cat": "code", "est": 15},
            {"desc": "全量测试验证", "deps": ["实施修复"], "cat": "test", "est": 10},
        ],
        "add_feature": [
            {"desc": "需求分析和设计", "deps": [], "cat": "design", "est": 20},
            {"desc": "实现核心逻辑", "deps": ["需求分析和设计"], "cat": "code", "est": 30},
            {"desc": "集成到现有系统", "deps": ["实现核心逻辑"], "cat": "integration", "est": 15},
            {"desc": "编写测试", "deps": ["集成到现有系统"], "cat": "test", "est": 15},
            {"desc": "文档更新", "deps": ["编写测试"], "cat": "docs", "est": 10},
        ],
        "deploy": [
            {"desc": "检查环境依赖", "deps": [], "cat": "setup", "est": 5},
            {"desc": "运行全量测试", "deps": ["检查环境依赖"], "cat": "test", "est": 10},
            {"desc": "构建产物", "deps": ["运行全量测试"], "cat": "build", "est": 10},
            {"desc": "上传服务器", "deps": ["构建产物"], "cat": "deploy", "est": 5},
            {"desc": "重启服务并验证", "deps": ["上传服务器"], "cat": "deploy", "est": 5},
        ],
    }

    def __init__(self):
        self._goals: Dict[str, Goal] = {}
        self._history: deque = deque(maxlen=50)
        self._id_counter: int = 0

    # ── Decomposition ──────────────────────────────────

    def decompose(self, goal_description: str,
                 goal_type: Optional[str] = None) -> Goal:
        """分解目标为子任务"""
        goal_id = f"goal-{int(time.time())}-{self._id_counter}"
        self._id_counter += 1

        # 1. 检测目标类型
        if goal_type is None:
            goal_type = self._detect_type(goal_description)

        # 2. 使用模板或生成通用分解
        template = self._TEMPLATES.get(goal_type)
        subtasks = []

        if template:
            # 从模板创建
            for i, t in enumerate(template):
                desc = t["desc"]
                # 用目标描述个性化
                if "{goal}" in desc:
                    desc = desc.replace("{goal}", goal_description[:50])

                subtasks.append(SubTask(
                    id=f"{goal_id}-{i+1}",
                    description=desc,
                    dependencies=[
                        f"{goal_id}-{template.index(d)+1}"
                        for d in template
                        if d["desc"] in t.get("deps", [])
                    ],
                    estimated_minutes=t.get("est", 10),
                    category=t.get("cat", "general"),
                ))
        else:
            # 通用分解: 分析→设计→实现→测试→部署
            steps = [
                ("分析需求和约束", "analysis", 10),
                ("设计方案", "design", 15),
                ("实现核心功能", "implementation", 30),
                ("编写测试验证", "testing", 15),
                ("集成和部署", "deployment", 10),
            ]
            for i, (desc, cat, est) in enumerate(steps):
                deps = [f"{goal_id}-{i}"] if i > 0 else []
                subtasks.append(SubTask(
                    id=f"{goal_id}-{i+1}",
                    description=desc,
                    dependencies=deps,
                    estimated_minutes=est,
                    category=cat,
                ))

        # 3. 计算初始就绪任务
        for st in subtasks:
            if not st.dependencies:
                st.status = TaskStatus.READY

        goal = Goal(
            id=goal_id,
            description=goal_description,
            subtasks=subtasks,
        )
        goal.progress = self._calc_progress(goal)

        self._goals[goal_id] = goal
        self._history.append(goal_id)

        return goal

    def _detect_type(self, description: str) -> str:
        """检测目标类型"""
        desc = description.lower()
        if any(kw in desc for kw in [
            "build", "create", "web", "app", "application",
            "构建", "创建", "网站", "应用",
        ]):
            return "build_web_app"
        if any(kw in desc for kw in [
            "fix", "bug", "debug", "修复", "bug", "错误",
        ]):
            return "fix_bug"
        if any(kw in desc for kw in [
            "add", "feature", "implement", "添加", "功能", "实现",
        ]):
            return "add_feature"
        if any(kw in desc for kw in [
            "deploy", "release", "publish", "部署", "发布",
        ]):
            return "deploy"
        return "generic"

    # ── Execution ──────────────────────────────────────

    def get_ready_tasks(self, goal_id: str) -> List[SubTask]:
        """获取可执行的就绪任务"""
        goal = self._goals.get(goal_id)
        if not goal:
            return []

        # 更新依赖状态
        self._refresh_dependencies(goal)

        ready = [
            st for st in goal.subtasks
            if st.status == TaskStatus.READY
        ]
        ready.sort(key=lambda t: (t.priority, t.estimated_minutes), reverse=True)
        return ready

    def start_task(self, goal_id: str, task_id: str):
        """开始执行任务"""
        goal = self._goals.get(goal_id)
        if not goal:
            return
        for st in goal.subtasks:
            if st.id == task_id:
                st.status = TaskStatus.RUNNING
                break

    def complete_task(self, goal_id: str, task_id: str,
                     result: str = ""):
        """完成任务"""
        goal = self._goals.get(goal_id)
        if not goal:
            return
        for st in goal.subtasks:
            if st.id == task_id:
                st.status = TaskStatus.COMPLETED
                st.result = result
                break

        self._refresh_dependencies(goal)
        goal.progress = self._calc_progress(goal)

    def fail_task(self, goal_id: str, task_id: str,
                 error: str = ""):
        """任务失败"""
        goal = self._goals.get(goal_id)
        if not goal:
            return
        for st in goal.subtasks:
            if st.id == task_id:
                st.status = TaskStatus.FAILED
                st.result = error
                # 阻塞下游
                for dep_st in goal.subtasks:
                    if task_id in dep_st.dependencies:
                        dep_st.status = TaskStatus.BLOCKED
                break

    def _refresh_dependencies(self, goal: Goal):
        """刷新依赖状态"""
        for st in goal.subtasks:
            if st.status in (TaskStatus.PENDING, TaskStatus.BLOCKED):
                all_deps_completed = all(
                    ds.status == TaskStatus.COMPLETED
                    for ds in goal.subtasks
                    if ds.id in st.dependencies
                )
                deps_exist = all(
                    any(ds.id == dep for ds in goal.subtasks)
                    for dep in st.dependencies
                )
                if deps_exist and all_deps_completed:
                    st.status = TaskStatus.READY

    def _calc_progress(self, goal: Goal) -> float:
        """计算进度"""
        if not goal.subtasks:
            return 0.0
        completed = sum(
            1 for st in goal.subtasks
            if st.status == TaskStatus.COMPLETED
        )
        return completed / len(goal.subtasks)

    # ── Stats ──────────────────────────────────────────

    def get_goal_status(self, goal_id: str) -> Optional[Dict]:
        """获取目标状态"""
        goal = self._goals.get(goal_id)
        if not goal:
            return None

        return {
            "id": goal.id,
            "description": goal.description,
            "progress": round(goal.progress * 100, 1),
            "total_tasks": len(goal.subtasks),
            "completed": sum(
                1 for st in goal.subtasks
                if st.status == TaskStatus.COMPLETED
            ),
            "running": sum(
                1 for st in goal.subtasks
                if st.status == TaskStatus.RUNNING
            ),
            "failed": sum(
                1 for st in goal.subtasks
                if st.status == TaskStatus.FAILED
            ),
            "ready": len(self.get_ready_tasks(goal_id)),
            "estimated_total_minutes": sum(
                st.estimated_minutes for st in goal.subtasks
            ),
            "tasks": [
                {
                    "id": st.id, "desc": st.description,
                    "status": st.status.value,
                    "deps": st.dependencies,
                    "category": st.category,
                    "est_min": st.estimated_minutes,
                }
                for st in goal.subtasks
            ],
        }

    def get_stats(self) -> Dict:
        return {
            "total_goals": len(self._goals),
            "active_goals": sum(
                1 for g in self._goals.values()
                if g.progress < 1.0
            ),
            "completed_goals": sum(
                1 for g in self._goals.values()
                if g.progress >= 1.0
            ),
        }


# 单例
_decomposer: Optional[GoalDecomposer] = None


def get_goal_decomposer() -> GoalDecomposer:
    global _decomposer
    if _decomposer is None:
        _decomposer = GoalDecomposer()
    return _decomposer
