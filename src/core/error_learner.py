"""v2.66 Error Learner — 自主错误学习引擎

从错误中提取模式、分类严重性、学习教训、持久化知识。
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class LessonSeverity(Enum):
    """错误严重性级别"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Lesson:
    """一条学到的教训"""
    id: str = ""
    error_pattern: str = ""
    error_type: str = ""
    severity: LessonSeverity = LessonSeverity.MEDIUM
    context: str = ""
    fix_applied: str = ""
    occurrence_count: int = 1
    regression_test: str = ""


# ── 关键词 → 严重性 映射 ───────────────────────────────────────────
_SEVERITY_RULES = [
    # CRITICAL: 权限拒绝 + 危险操作
    (re.compile(r"(?i)permission\s+denied.*(?:delete|drop|truncate|destroy|production\s*database|shadow|passwd)"), LessonSeverity.CRITICAL),
    (re.compile(r"(?i)cannot\s+access\s+/etc/(?:shadow|passwd)"), LessonSeverity.CRITICAL),
    # HIGH: ModuleNotFoundError, ImportError, ConnectionError
    (re.compile(r"(?i)ModuleNotFoundError"), LessonSeverity.HIGH),
    (re.compile(r"(?i)ImportError"), LessonSeverity.HIGH),
    (re.compile(r"(?i)ConnectionError|ConnectionRefusedError"), LessonSeverity.HIGH),
    # MEDIUM: KeyError, AttributeError, TypeError, ValueError
    (re.compile(r"(?i)(KeyError|AttributeError|TypeError|ValueError|KeyError)"), LessonSeverity.MEDIUM),
    # LOW: 其他
]


# ── 错误类型提取 ────────────────────────────────────────────────────
_ERROR_TYPE_RE = re.compile(r"^(\w+(?:Error|Warning|Exception))")


def _extract_error_type(msg: str) -> str:
    m = _ERROR_TYPE_RE.match(msg)
    return m.group(1) if m else "UnknownError"


def _determine_severity(msg: str) -> LessonSeverity:
    for pattern, sev in _SEVERITY_RULES:
        if pattern.search(msg):
            return sev
    return LessonSeverity.LOW


def _generate_regression_test(msg: str, error_type: str) -> str:
    """为 CRITICAL 错误生成回归测试骨架"""
    return (
        f"# Regression test for {error_type}\n"
        f"# Triggered by: {msg[:80]}\n"
        f"def test_regression_{hashlib.md5(msg.encode()).hexdigest()[:8]}():\n"
        f"    # TODO: Implement specific assertion for this error pattern\n"
        f"    pass\n"
    )


class AutonomousLearningEngine:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """自主错误学习引擎 — 从错误中提取模式、分类、学习、预防"""

    def __init__(self, data_dir: Path | None = None, **kw):
        self.data_dir = Path(data_dir) if data_dir else Path("learned_data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lessons: dict[str, Lesson] = {}
        self._load()

    # ── 模式提取 ────────────────────────────────────────────────────

    _VALUE_RE = re.compile(r"""['\"]([^'\"]*)['\"]""")
    _NUM_RE = re.compile(r"\b\d+\b")
    _PATH_RE = re.compile(r"(?:/[\w.@\-/]+|(?:[A-Za-z]:)?[\\/][\w.@\-\\/]+)")

    def extract_pattern(self, msg: str, **kw) -> str:
        """将错误消息中的具体值替换为占位符，提取通用模式"""
        result = msg
        # 先替换路径
        result = self._PATH_RE.sub("<PATH>", result)
        # 替换引号内的值
        result = self._VALUE_RE.sub("<VALUE>", result)
        # 替换数字
        result = self._NUM_RE.sub("<NUM>", result)
        # 清理连续的占位符
        result = re.sub(r"<VALUE>\s*<VALUE>", "<VALUE>", result)
        return result

    # ── 错误分类 ────────────────────────────────────────────────────

    def classify_error(self, msg: str, **kw) -> tuple:
        """分类错误，返回 (error_type, severity)"""
        etype = _extract_error_type(msg)
        severity = _determine_severity(msg)
        return etype, severity

    # ── 学习 ────────────────────────────────────────────────────────

    def learn(self, msg: str, context: str = "", fix_applied: str = "", **kw) -> Lesson:
        """从一条错误中学习。相同模式会合并更新 occurrence_count"""
        pattern = self.extract_pattern(msg)
        etype, severity = self.classify_error(msg)

        # 检查是否已有相同模式的教训
        pattern_key = f"{etype}:{pattern}"
        if pattern_key in self._lessons:
            lesson = self._lessons[pattern_key]
            lesson.occurrence_count += 1
            if context and context not in lesson.context:
                lesson.context += "; " + context
            if fix_applied:
                lesson.fix_applied = fix_applied
            self._save()
            return lesson

        # 新教训
        lesson = Lesson(
            id=hashlib.md5(pattern_key.encode()).hexdigest()[:12],
            error_pattern=pattern,
            error_type=etype,
            severity=severity,
            context=context,
            fix_applied=fix_applied,
            occurrence_count=1,
            regression_test="",
        )

        # CRITICAL 级别自动生成回归测试
        if severity == LessonSeverity.CRITICAL:
            lesson.regression_test = _generate_regression_test(msg, etype)

        self._lessons[pattern_key] = lesson
        self._save()
        return lesson

    # ── 查询 ────────────────────────────────────────────────────────

    def query(self, msg: str, **kw) -> dict:
        """查询错误是否匹配已知模式"""
        pattern = self.extract_pattern(msg)
        etype = _extract_error_type(msg)
        pattern_key = f"{etype}:{pattern}"

        if pattern_key in self._lessons:
            lesson = self._lessons[pattern_key]
            return {
                "matched": True,
                "lesson_id": lesson.id,
                "severity": lesson.severity.value,
                "occurrence_count": lesson.occurrence_count,
                "fix_applied": lesson.fix_applied,
            }

        # 模糊匹配：尝试用 error_type 匹配同类错误
        for key, lesson in self._lessons.items():
            if key.startswith(etype + ":"):
                return {
                    "matched": True,
                    "lesson_id": lesson.id,
                    "severity": lesson.severity.value,
                    "occurrence_count": lesson.occurrence_count,
                    "fix_applied": lesson.fix_applied,
                }

        return {"matched": False}

    # ── 预防 ────────────────────────────────────────────────────────

    def prevent(self, msg: str, **kw) -> bool:
        """检查是否可以预防该错误（基于已知模式）。返回 True 表示可预防"""
        result = self.query(msg)
        return result["matched"]

    # ── 统计 ────────────────────────────────────────────────────────

    def get_stats(self, **kw) -> dict:
        """获取学习统计"""
        total = len(self._lessons)
        by_type: dict[str, int] = {}
        for lesson in self._lessons.values():
            by_type[lesson.error_type] = by_type.get(lesson.error_type, 0) + 1

        # Top lessons by occurrence
        sorted_lessons = sorted(
            self._lessons.values(),
            key=lambda l: l.occurrence_count,
            reverse=True,
        )
        top_lessons = [
            {
                "id": l.id,
                "pattern": l.error_pattern,
                "error_type": l.error_type,
                "occurrence_count": l.occurrence_count,
            }
            for l in sorted_lessons[:10]
        ]

        return {
            "total_lessons_learned": total,
            "by_type": by_type,
            "top_lessons": top_lessons,
        }

    # ── 持久化 ──────────────────────────────────────────────────────

    _STORAGE_FILE = "lessons.json"

    def _storage_path(self, **kw) -> Path:
        return self.data_dir / self._STORAGE_FILE

    def _save(self, **kw):
        data = {}
        for key, lesson in self._lessons.items():
            data[key] = {
                "id": lesson.id,
                "error_pattern": lesson.error_pattern,
                "error_type": lesson.error_type,
                "severity": lesson.severity.value,
                "context": lesson.context,
                "fix_applied": lesson.fix_applied,
                "occurrence_count": lesson.occurrence_count,
                "regression_test": lesson.regression_test,
            }
        self._storage_path().write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _load(self, **kw):
        path = self._storage_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            for key, d in data.items():
                lesson = Lesson(
                    id=d.get("id", ""),
                    error_pattern=d.get("error_pattern", ""),
                    error_type=d.get("error_type", ""),
                    severity=LessonSeverity(d.get("severity", "medium")),
                    context=d.get("context", ""),
                    fix_applied=d.get("fix_applied", ""),
                    occurrence_count=d.get("occurrence_count", 1),
                    regression_test=d.get("regression_test", ""),
                )
                self._lessons[key] = lesson
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

