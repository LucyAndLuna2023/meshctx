"""Cross-Project Context Restorer — v2.70
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
解决: "Every new repo starts from zero"

打开项目时自动恢复:
1. 历史对话上下文快照
2. 项目配置和偏好
3. 学习的教训(哪些改动好/坏)
4. 常用命令和习惯
5. 跨项目知识复用
"""
import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProjectContext:
    """项目上下文快照"""
    project_id: str
    project_name: str
    project_path: str
    language: str = ""
    framework: str = ""
    last_opened: float = 0.0
    conversation_count: int = 0
    lessons_learned: List[str] = field(default_factory=list)
    common_commands: List[str] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)
    file_patterns: List[str] = field(default_factory=list)
    git_branch: str = ""
    test_command: str = ""


class ContextRestorer:
    """跨项目上下文恢复器"""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path.home() / ".meshctx" / "projects"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._contexts: Dict[str, ProjectContext] = {}
        self._global_lessons: List[str] = []
        self._load_all()

    # ── Persistence ────────────────────────────────────

    def _load_all(self):
        """加载所有项目上下文"""
        for ctx_file in self.data_dir.glob("*.json"):
            try:
                data = json.loads(ctx_file.read_text())
                ctx = ProjectContext(**data)
                self._contexts[ctx.project_id] = ctx
            except Exception:
                pass

        # 加载全局教训
        global_file = self.data_dir / "_global_lessons.json"
        if global_file.exists():
            try:
                self._global_lessons = json.loads(global_file.read_text())
            except Exception:
                pass

        logger.info(f"加载 {len(self._contexts)} 个项目上下文")

    def _save_ctx(self, ctx: ProjectContext):
        ctx_file = self.data_dir / f"{ctx.project_id}.json"
        ctx_file.write_text(json.dumps({
            k: v for k, v in ctx.__dict__.items()
        }, indent=2, ensure_ascii=False))

    def _save_global(self):
        (self.data_dir / "_global_lessons.json").write_text(
            json.dumps(self._global_lessons, indent=2, ensure_ascii=False)
        )

    # ── Project Detection ──────────────────────────────

    def detect_project(self, path: Path) -> ProjectContext:
        """检测项目并创建/更新上下文"""
        path = path.resolve()
        pid = hashlib.md5(str(path).encode()).hexdigest()[:16]

        # 已有上下文则更新
        if pid in self._contexts:
            ctx = self._contexts[pid]
            ctx.last_opened = time.time()
            self._save_ctx(ctx)
            return ctx

        # 新建上下文
        ctx = ProjectContext(
            project_id=pid,
            project_name=path.name,
            project_path=str(path),
            last_opened=time.time(),
        )

        # 自动检测项目属性
        ctx.language = self._detect_language(path)
        ctx.framework = self._detect_framework(path)
        ctx.file_patterns = self._detect_file_patterns(path)
        ctx.git_branch = self._detect_git_branch(path)
        ctx.test_command = self._detect_test_command(path)

        self._contexts[pid] = ctx
        self._save_ctx(ctx)
        return ctx

    def _detect_language(self, path: Path) -> str:
        """检测主要语言"""
        counts = defaultdict(int)
        for ext, lang in {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".rs": "Rust", ".go": "Go", ".java": "Java",
            ".cpp": "C++", ".c": "C", ".rb": "Ruby",
        }.items():
            counts[lang] = len(list(path.rglob(f"*{ext}")))

        if not counts:
            return "Unknown"
        return max(counts, key=counts.get)

    def _detect_framework(self, path: Path) -> str:
        """检测框架"""
        checks = {
            "FastAPI": ["fastapi"],
            "Flask": ["flask"],
            "Django": ["django"],
            "React": ["react"],
            "Next.js": ["next"],
            "Vue": ["vue"],
            "Spring": ["spring"],
            "PyTorch": ["torch"],
            "TensorFlow": ["tensorflow"],
        }

        # 检查requirements.txt/pyproject.toml/package.json
        for req_file in ["requirements.txt", "pyproject.toml", "package.json"]:
            rf = path / req_file
            if rf.exists():
                try:
                    content = rf.read_text().lower()
                    for fw, keywords in checks.items():
                        if any(kw in content for kw in keywords):
                            return fw
                except Exception:
                    pass

        return ""

    def _detect_file_patterns(self, path: Path) -> List[str]:
        """检测常用文件模式"""
        patterns = set()
        for f in list(path.rglob("*.py"))[:100]:
            p = str(f.relative_to(path))
            # 提取目录模式: src/core/*.py, tests/*.py 等
            parts = p.split("/")
            if len(parts) >= 2:
                patterns.add(f"{parts[0]}/*.{f.suffix}")
        return sorted(patterns)[:10]

    def _detect_git_branch(self, path: Path) -> str:
        """检测git分支"""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(path), capture_output=True, text=True, timeout=5
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def _detect_test_command(self, path: Path) -> str:
        """检测测试命令"""
        if (path / "pyproject.toml").exists():
            return "pytest"
        if (path / "Makefile").exists():
            return "make test"
        if (path / "package.json").exists():
            return "npm test"
        return "pytest"  # default

    # ── Context Restoration ────────────────────────────

    def restore(self, path: Path) -> Dict[str, Any]:
        """恢复项目上下文"""
        ctx = self.detect_project(path)

        # 收集跨项目全球教训
        global_relevant = [
            g for g in self._global_lessons
            if ctx.language.lower() in g.lower()
        ][:5] if ctx.language else self._global_lessons[:3]

        # 相关项目的教训
        related = self._find_related_projects(ctx)

        return {
            "project": {
                "name": ctx.project_name,
                "language": ctx.language,
                "framework": ctx.framework,
                "git_branch": ctx.git_branch,
                "test_command": ctx.test_command,
            },
            "context": {
                "last_opened": ctx.last_opened,
                "conversations": ctx.conversation_count,
                "lessons_count": len(ctx.lessons_learned),
            },
            "lessons": ctx.lessons_learned[-10:],
            "global_lessons": global_relevant,
            "common_commands": ctx.common_commands[-5:],
            "related_projects": [
                {"name": r.project_name, "language": r.language,
                 "framework": r.framework}
                for r in related[:5]
            ],
            "file_patterns": ctx.file_patterns,
        }

    # ── Learning ───────────────────────────────────────

    def learn_lesson(self, path: Path, lesson: str,
                    global_lesson: bool = False):
        """记录教训"""
        ctx = self.detect_project(path)
        ctx.lessons_learned.append(lesson)
        # 保持最近50条
        if len(ctx.lessons_learned) > 50:
            ctx.lessons_learned = ctx.lessons_learned[-50:]
        self._save_ctx(ctx)

        if global_lesson:
            self._global_lessons.append(lesson)
            if len(self._global_lessons) > 100:
                self._global_lessons = self._global_lessons[-100:]
            self._save_global()

    def learn_command(self, path: Path, command: str):
        """记录常用命令"""
        ctx = self.detect_project(path)
        if command not in ctx.common_commands:
            ctx.common_commands.append(command)
            if len(ctx.common_commands) > 20:
                ctx.common_commands = ctx.common_commands[-20:]
            self._save_ctx(ctx)

    def record_conversation(self, path: Path):
        """记录一次对话"""
        ctx = self.detect_project(path)
        ctx.conversation_count += 1
        ctx.last_opened = time.time()
        self._save_ctx(ctx)

    # ── Cross-Project ──────────────────────────────────

    def _find_related_projects(self, ctx: ProjectContext) -> List[ProjectContext]:
        """查找相关项目"""
        related = []
        for pid, other in self._contexts.items():
            if pid == ctx.project_id:
                continue
            score = 0
            if other.language == ctx.language:
                score += 3
            if other.framework == ctx.framework and ctx.framework:
                score += 5
            if score > 0:
                related.append((score, other))

        related.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in related]

    def transfer_knowledge(self, from_path: Path,
                          to_path: Path) -> Dict:
        """项目间知识迁移"""
        from_ctx = self.detect_project(from_path)
        to_ctx = self.detect_project(to_path)

        transferred = []

        # 迁移教训
        for lesson in from_ctx.lessons_learned:
            if lesson not in to_ctx.lessons_learned:
                to_ctx.lessons_learned.append(lesson)
                transferred.append(lesson[:100])

        # 迁移命令
        for cmd in from_ctx.common_commands:
            if cmd not in to_ctx.common_commands:
                to_ctx.common_commands.append(cmd)

        # 迁移偏好
        for k, v in from_ctx.preferences.items():
            if k not in to_ctx.preferences:
                to_ctx.preferences[k] = v

        self._save_ctx(to_ctx)

        return {
            "from": from_ctx.project_name,
            "to": to_ctx.project_name,
            "lessons_transferred": len(transferred),
            "commands_transferred": len(from_ctx.common_commands),
        }

    # ── Stats ──────────────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "total_projects": len(self._contexts),
            "global_lessons": len(self._global_lessons),
            "projects_by_language": dict(
                self._count_by("language")
            ),
            "recent_projects": sorted(
                [
                    {"name": c.project_name, "language": c.language,
                     "last_opened": c.last_opened}
                    for c in self._contexts.values()
                ],
                key=lambda x: x["last_opened"], reverse=True
            )[:5],
        }

    def _count_by(self, attr: str) -> Dict[str, int]:
        counts = defaultdict(int)
        for ctx in self._contexts.values():
            val = getattr(ctx, attr, "")
            if val:
                counts[val] += 1
        return dict(counts)

    def list_projects(self) -> List[Dict]:
        return [
            {
                "id": c.project_id,
                "name": c.project_name,
                "language": c.language,
                "framework": c.framework,
                "conversations": c.conversation_count,
                "last_opened": c.last_opened,
            }
            for c in self._contexts.values()
        ]


# 单例
_restorer: Optional[ContextRestorer] = None


def get_context_restorer() -> ContextRestorer:
    global _restorer
    if _restorer is None:
        _restorer = ContextRestorer()
    return _restorer
