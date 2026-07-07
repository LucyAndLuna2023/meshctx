"""meshctx context_restorer — project context detection, restoration, and knowledge transfer"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProjectContext:
    """Detected project context."""
    project_id: str
    project_name: str
    language: str
    root_path: str = ""
    framework: str = ""
    file_patterns: list[str] = field(default_factory=list)
    test_command: str = ""
    conversation_count: int = 0
    lessons: list[str] = field(default_factory=list)
    common_commands: list[str] = field(default_factory=list)
    detected_at: float = 0.0
    last_restored: float = 0.0


class ContextRestorer:
    """Context restoration engine for project re-entry."""

    def __init__(self, data_dir: Path | str | None = None, *args, **kwargs):
        if data_dir is None:
            data_dir = kwargs.get("data_dir", Path("/tmp/context_restorer"))
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._contexts: dict[str, ProjectContext] = {}
        self._project_paths: dict[str, str] = {}

    # ── Project Detection ──

    def detect_project(self, project_path: Path | str) -> ProjectContext:
        """Detect project context from a given path."""
        project_path = Path(project_path)
        project_name = project_path.name
        language = self._detect_language(project_path)
        framework = self._detect_framework(project_path)
        file_patterns = self._detect_file_patterns(project_path)
        test_command = self._detect_test_command(project_path)

        project_id = self._make_project_id(str(project_path), project_name)

        ctx = self._contexts.get(project_id)
        if not ctx:
            ctx = ProjectContext(
                project_id=project_id,
                project_name=project_name,
                language=language,
                root_path=str(project_path),
                framework=framework,
                file_patterns=file_patterns,
                test_command=test_command,
                detected_at=time.time(),
            )
            self._contexts[project_id] = ctx
            self._project_paths[project_id] = str(project_path)

        return ctx

    def _make_project_id(self, path_str: str, name: str) -> str:
        return hashlib.md5((path_str + name).encode()).hexdigest()[:12]

    def _detect_language(self, project_path: Path) -> str:
        """Detect the primary language of a project."""
        signals = {
            "Python": [".py", "requirements.txt", "setup.py", "pyproject.toml", "Pipfile"],
            "TypeScript": [".ts", ".tsx", "tsconfig.json"],
            "JavaScript": [".js", ".jsx", "package.json", "node_modules"],
            "Rust": [".rs", "Cargo.toml", "Cargo.lock"],
            "Go": [".go", "go.mod", "go.sum"],
            "Java": [".java", "pom.xml", "build.gradle"],
            "Ruby": [".rb", "Gemfile", "Rakefile"],
            "C++": [".cpp", ".hpp", ".cc", "CMakeLists.txt"],
            "C": [".c", ".h", "Makefile"],
        }

        counts: dict[str, int] = defaultdict(int)
        files = list(project_path.rglob("*"))[:500]

        for f in files:
            if f.is_file():
                for lang, patterns in signals.items():
                    if f.suffix in patterns or f.name in patterns:
                        counts[lang] += 1

        if counts:
            return max(counts, key=counts.get)

        # Default fallback
        py_files = list(project_path.glob("*.py"))
        if py_files:
            return "Python"
        return "Unknown"

    def _detect_framework(self, project_path: Path) -> str:
        """Detect framework used by the project."""
        framework_signals = {
            "FastAPI": ["fastapi", "uvicorn"],
            "Flask": ["flask", "werkzeug"],
            "Django": ["django"],
            "Fast": ["fastapi"],
            "React": ["react", "react-dom"],
            "Vue": ["vue"],
            "Next.js": ["next"],
            "Express": ["express"],
            "Spring Boot": ["spring-boot"],
            "Rocket": ["rocket"],
            "Actix": ["actix"],
            "Gin": ["gin-gonic"],
        }

        req_files = [
            project_path / "requirements.txt",
            project_path / "pyproject.toml",
            project_path / "Pipfile",
            project_path / "setup.py",
            project_path / "package.json",
            project_path / "Cargo.toml",
            project_path / "go.mod",
            project_path / "pom.xml",
            project_path / "build.gradle",
        ]

        for rf in req_files:
            if rf.exists():
                try:
                    content = rf.read_text()
                    for fw, keywords in framework_signals.items():
                        content_lower = content.lower()
                        for kw in keywords:
                            if kw.lower() in content_lower:
                                return fw
                except Exception:
                    pass

        return ""

    def _detect_file_patterns(self, project_path: Path) -> list[str]:
        """Detect file patterns in the project."""
        patterns: list[str] = []
        ext_counts: dict[str, int] = defaultdict(int)
        for f in project_path.glob("**/*"):
            if f.is_file() and f.suffix:
                ext_counts[f.suffix] += 1

        top_exts = sorted(ext_counts, key=ext_counts.get, reverse=True)[:5]
        for ext in top_exts:
            patterns.append(f"*{ext}")

        # Also add known config patterns
        config_files = [".gitignore", "Makefile", "Dockerfile", ".env", "README.md"]
        for cf in config_files:
            if (project_path / cf).exists():
                patterns.append(cf)

        return patterns

    def _detect_test_command(self, project_path: Path) -> str:
        """Detect the test command for the project."""
        lang = self._detect_language(project_path)

        if lang == "Python":
            if (project_path / "requirements.txt").exists():
                req = (project_path / "requirements.txt").read_text()
                if "pytest" in req:
                    return "pytest"
            if (project_path / "pyproject.toml").exists():
                pyproj = (project_path / "pyproject.toml").read_text()
                if "pytest" in pyproj:
                    return "pytest"
            if list(project_path.glob("**/test_*.py")) or list(project_path.glob("**/*_test.py")):
                return "pytest"
            return "python -m unittest"
        elif lang == "JavaScript":
            return "npm test"
        elif lang == "Rust":
            return "cargo test"
        elif lang == "Go":
            return "go test ./..."
        else:
            return "make test"

    # ── Context Restoration ──

    def restore(self, project_path: Path | str) -> dict[str, Any]:
        """Restore full context for a project."""
        ctx = self.detect_project(project_path)
        ctx.last_restored = time.time()

        if not self._contexts.get(ctx.project_id):
            self._contexts[ctx.project_id] = ctx

        related = self._find_related_projects(ctx)

        return {
            "project": {
                "id": ctx.project_id,
                "name": ctx.project_name,
                "language": ctx.language,
                "framework": ctx.framework,
                "root_path": ctx.root_path,
                "file_patterns": ctx.file_patterns,
                "test_command": ctx.test_command,
            },
            "lessons": list(ctx.lessons),
            "common_commands": list(ctx.common_commands),
            "related_projects": [r.project_name for r in related],
            "conversation_count": ctx.conversation_count,
            "detected_at": ctx.detected_at,
            "last_restored": ctx.last_restored,
        }

    # ── Learning ──

    def learn_lesson(self, project_path: Path | str, lesson: str):
        """Record a lesson learned from a project."""
        ctx = self.detect_project(project_path)
        ctx.lessons.append(lesson)

    def learn_command(self, project_path: Path | str, command: str):
        """Record a common command for a project."""
        ctx = self.detect_project(project_path)
        ctx.common_commands.append(command)

    def record_conversation(self, project_path: Path | str):
        """Record a conversation interaction with the project."""
        ctx = self.detect_project(project_path)
        ctx.conversation_count += 1

    # ── Cross-Project ──

    def _find_related_projects(self, ctx: ProjectContext) -> list[ProjectContext]:
        """Find projects related to the given context."""
        related = []
        for pid, other in self._contexts.items():
            if pid == ctx.project_id:
                continue
            if other.language == ctx.language:
                related.append(other)
            elif other.framework and other.framework == ctx.framework:
                related.append(other)
        return related

    def transfer_knowledge(self, source_path: Path | str,
                           target_path: Path | str) -> dict[str, Any]:
        """Transfer lessons and knowledge from one project to another."""
        src_ctx = self.detect_project(source_path)
        tgt_ctx = self.detect_project(target_path)

        transferred = 0
        for lesson in src_ctx.lessons:
            if lesson not in tgt_ctx.lessons:
                tgt_ctx.lessons.append(lesson)
                transferred += 1

        return {
            "source": src_ctx.project_name,
            "target": tgt_ctx.project_name,
            "lessons_transferred": transferred,
        }

    # ── Stats ──

    def list_projects(self) -> list[dict]:
        """List all known projects."""
        result = []
        for pid, ctx in self._contexts.items():
            result.append({
                "id": ctx.project_id,
                "name": ctx.project_name,
                "language": ctx.language,
                "framework": ctx.framework,
                "conversation_count": ctx.conversation_count,
                "last_restored": ctx.last_restored,
            })
        return result

    def get_stats(self) -> dict[str, Any]:
        """Get overall statistics."""
        projects = self.list_projects()
        recent = sorted(projects, key=lambda p: p.get("last_restored", 0), reverse=True)[:10]

        return {
            "total_projects": len(projects),
            "recent_projects": recent,
            "total_lessons": sum(len(c.lessons) for c in self._contexts.values()),
            "total_commands": sum(len(c.common_commands) for c in self._contexts.values()),
            "total_conversations": sum(c.conversation_count for c in self._contexts.values()),
        }
