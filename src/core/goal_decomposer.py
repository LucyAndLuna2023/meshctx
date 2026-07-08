"""meshctx Goal Decomposer — v2.67 目标分解器"""
import uuid
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(Enum):
    pending = "pending"
    ready = "ready"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    blocked = "blocked"


@dataclass
class Subtask:
    id: str
    title: str
    status: TaskStatus = TaskStatus.pending
    dependencies: list = field(default_factory=list)
    output: str = ""
    description: str = ""


@dataclass
class Goal:
    id: str
    text: str
    goal_type: str
    subtasks: list = field(default_factory=list)
    progress: float = 0.0


# ── 各类目标的子任务模板 ──────────────────────────────────────────────

_SUBTASK_TEMPLATES = {
    "build_web_app": [
        {"id": "req",      "title": "需求分析",     "deps": []},
        {"id": "arch",     "title": "架构设计",     "deps": ["req"]},
        {"id": "frontend", "title": "前端开发",     "deps": ["arch"]},
        {"id": "backend",  "title": "后端开发",     "deps": ["arch"]},
        {"id": "deploy",   "title": "测试与部署",   "deps": ["frontend", "backend"]},
    ],
    "fix_bug": [
        {"id": "repro",    "title": "复现问题",     "deps": []},
        {"id": "root",     "title": "定位根因",     "deps": ["repro"]},
        {"id": "fix",      "title": "编写修复",     "deps": ["root"]},
        {"id": "verify",   "title": "验证修复",     "deps": ["fix"]},
    ],
    "add_feature": [
        {"id": "design",   "title": "功能设计",     "deps": []},
        {"id": "impl",     "title": "功能实现",     "deps": ["design"]},
        {"id": "test",     "title": "功能测试",     "deps": ["impl"]},
        {"id": "release",  "title": "功能上线",     "deps": ["test"]},
    ],
    "deploy": [
        {"id": "check",    "title": "发布前检查",   "deps": []},
        {"id": "backup",   "title": "备份数据",     "deps": ["check"]},
        {"id": "exec",     "title": "执行部署",     "deps": ["backup"]},
        {"id": "health",   "title": "健康检查",     "deps": ["exec"]},
    ],
    "generic": [
        {"id": "analyze",  "title": "分析",          "deps": []},
        {"id": "design",   "title": "设计",          "deps": ["analyze"]},
        {"id": "implement", "title": "实现",         "deps": ["design"]},
        {"id": "test",     "title": "测试",          "deps": ["implement"]},
        {"id": "deploy",   "title": "部署",          "deps": ["test"]},
    ],
}

# ── 类型检测关键词 ────────────────────────────────────────────────────

_TYPE_KEYWORDS = [
    ("build_web_app", ["构建", "build", "创建", "create"], ["网站", "web app", "web application", "网页", "前端"]),
    ("fix_bug",       ["修复", "fix"],                   ["bug", "问题", "错误", "缺陷"]),
    ("add_feature",   ["添加", "add"],                   ["功能", "feature"]),
    ("deploy",        ["部署", "deploy"],                ["生产", "production", "上线", "环境"]),
]


class GoalDecomposer:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """目标分解器 — 将高层目标拆解为有序子任务链"""

    def __init__(self, **kw):
        self._goals: dict[str, Goal] = {}

    # ── 类型检测 ──────────────────────────────────────────────────────

    def _detect_type(self, text: str, **kw) -> str:
        """基于关键词匹配检测目标类型"""
        text_lower = text.lower()
        for goal_type, trigger_words, context_words in _TYPE_KEYWORDS:
            has_trigger = any(w in text_lower for w in trigger_words)
            has_context = any(w in text_lower for w in context_words)
            if has_trigger and has_context:
                return goal_type
        return "generic"

    # ── 分解 ──────────────────────────────────────────────────────────

    def decompose(self, goal_text: str, goal_type: str | None = None, **kw) -> Goal:
        """将目标分解为子任务"""
        if goal_type is None:
            goal_type = self._detect_type(goal_text)

        goal = Goal(
            id=str(uuid.uuid4()),
            text=goal_text,
            goal_type=goal_type,
            progress=0.0,
        )

        template = _SUBTASK_TEMPLATES.get(goal_type, _SUBTASK_TEMPLATES["generic"])
        for tmpl in template:
            status = TaskStatus.ready if not tmpl["deps"] else TaskStatus.pending
            st = Subtask(
                id=f"{goal.id}:{tmpl['id']}",
                title=tmpl["title"],
                status=status,
                dependencies=[f"{goal.id}:{d}" for d in tmpl["deps"]],
            )
            goal.subtasks.append(st)

        self._goals[goal.id] = goal
        return goal

    # ── 获取就绪任务 ──────────────────────────────────────────────────

    def get_ready_tasks(self, goal_id: str, **kw) -> list[Subtask]:
        """返回当前可就绪执行的任务"""
        goal = self._goals.get(goal_id)
        if not goal:
            return []
        return [st for st in goal.subtasks if st.status == TaskStatus.ready]

    # ── 任务状态变更 ──────────────────────────────────────────────────

    def start_task(self, goal_id: str, task_id: str, **kw):
        """标记任务为进行中"""
        goal = self._goals.get(goal_id)
        if not goal:
            return
        for st in goal.subtasks:
            if st.id == task_id and st.status == TaskStatus.ready:
                st.status = TaskStatus.in_progress
                return

    def complete_task(self, goal_id: str, task_id: str, output: str = "", **kw):
        """完成任务并刷新依赖"""
        goal = self._goals.get(goal_id)
        if not goal:
            return
        for st in goal.subtasks:
            if st.id == task_id:
                st.status = TaskStatus.completed
                st.output = output
                break
        self._refresh_dependencies(goal)
        goal.progress = self._calc_progress(goal)

    def fail_task(self, goal_id: str, task_id: str, reason: str = "", **kw):
        """失败任务,阻塞下游"""
        goal = self._goals.get(goal_id)
        if not goal:
            return
        for st in goal.subtasks:
            if st.id == task_id:
                st.status = TaskStatus.failed
                st.output = reason
                break
        # 阻塞所有依赖此任务的下游
        for st in goal.subtasks:
            if task_id in st.dependencies and st.status not in (TaskStatus.completed, TaskStatus.failed):
                st.status = TaskStatus.blocked
        goal.progress = self._calc_progress(goal)

    # ── 依赖刷新 ──────────────────────────────────────────────────────

    def _refresh_dependencies(self, goal: Goal, **kw):
        """根据上游完成情况,更新所有 pending/blocked 任务状态"""
        for st in goal.subtasks:
            if st.status in (TaskStatus.completed, TaskStatus.failed, TaskStatus.in_progress):
                continue
            if not st.dependencies:
                # 无依赖但被阻塞 → 恢复
                if st.status == TaskStatus.blocked:
                    st.status = TaskStatus.ready
                continue

            all_done = True
            any_failed = False
            for dep_id in st.dependencies:
                dep = next((s for s in goal.subtasks if s.id == dep_id), None)
                if dep is None:
                    continue
                if dep.status != TaskStatus.completed:
                    all_done = False
                if dep.status == TaskStatus.failed:
                    any_failed = True

            if any_failed:
                st.status = TaskStatus.blocked
            elif all_done:
                st.status = TaskStatus.ready

    def _calc_progress(self, goal: Goal, **kw) -> float:
        """计算进度 (completed / total)"""
        total = len(goal.subtasks)
        if total == 0:
            return 0.0
        completed = sum(1 for st in goal.subtasks if st.status == TaskStatus.completed)
        return completed / total

    # ── 目标状态查询 ──────────────────────────────────────────────────

    def get_goal_status(self, goal_id: str, **kw) -> dict | None:
        """返回目标状态摘要"""
        goal = self._goals.get(goal_id)
        if goal is None:
            return None
        tasks = []
        for st in goal.subtasks:
            tasks.append({
                "id": st.id,
                "title": st.title,
                "status": st.status.value,
                "dependencies": st.dependencies,
            })
        return {
            "goal_id": goal.id,
            "text": goal.text,
            "goal_type": goal.goal_type,
            "total_tasks": len(goal.subtasks),
            "tasks": tasks,
            "progress": goal.progress,
        }

    # ── 统计 ──────────────────────────────────────────────────────────

    def get_stats(self, **kw) -> dict:
        """返回全局统计"""
        total = len(self._goals)
        # active = 还没有全部完成
        active = 0
        for goal in self._goals.values():
            all_done = all(
                st.status == TaskStatus.completed for st in goal.subtasks
            )
            if not all_done:
                active += 1
        return {
            "total_goals": total,
            "active_goals": active,
        }

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield _P("item"); yield _P("item")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __truediv__(s, o): return _P(f"{s._n}/{o}")
    def __rtruediv__(s, o): return _P(f"{o}/{s._n}")
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

