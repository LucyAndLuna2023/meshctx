"""Autonomous Error Learning Engine (ALiFE) — v2.66
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
直接解决: "Same hallucination 5 times today" "Agent fixes bug→reintroduces it"

从每次错误中学习:
1. 捕获错误 → 分类 → 提取模式 → 存储教训
2. 下次遇到相同模式 → 自动预警/阻止
3. 跨会话持久化 → 永不重复犯错
4. 渐进式学习 → 新错误加入知识库
"""
import hashlib
import json
import logging
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class LessonSeverity(Enum):
    """教训严重程度"""
    CRITICAL = "critical"   # 导致系统崩溃/数据丢失
    HIGH = "high"           # 功能不可用
    MEDIUM = "medium"       # 影响体验
    LOW = "low"             # 可忽略


@dataclass
class ErrorLesson:
    """一个错误教训"""
    id: str = ""
    error_type: str = ""          # KeyError, ImportError, etc.
    error_pattern: str = ""       # 正则模式匹配
    context: str = ""             # 发生场景
    root_cause: str = ""          # 根本原因
    fix_strategy: str = ""        # 修复策略
    severity: LessonSeverity = LessonSeverity.MEDIUM
    occurrence_count: int = 1
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    prevented_count: int = 0      # 被预防的次数
    regression_test: str = ""     # 生成的回归测试代码


class AutonomousLearningEngine:
    """自主错误学习引擎"""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path.home() / ".meshctx" / "learned_errors"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lessons: Dict[str, ErrorLesson] = {}
        self._error_history: deque = deque(maxlen=200)
        self._prevention_log: deque = deque(maxlen=100)
        self._load()

    # ── Persistence ────────────────────────────────────

    def _load(self):
        """加载已学习的教训"""
        lesson_file = self.data_dir / "lessons.json"
        if lesson_file.exists():
            try:
                data = json.loads(lesson_file.read_text())
                for lid, ldata in data.items():
                    lesson = ErrorLesson(
                        id=lid,
                        error_type=ldata.get("error_type", ""),
                        error_pattern=ldata.get("error_pattern", ""),
                        context=ldata.get("context", ""),
                        root_cause=ldata.get("root_cause", ""),
                        fix_strategy=ldata.get("fix_strategy", ""),
                        severity=LessonSeverity(ldata.get("severity", "medium")),
                        occurrence_count=ldata.get("occurrence_count", 1),
                        first_seen=ldata.get("first_seen", time.time()),
                        last_seen=ldata.get("last_seen", time.time()),
                        prevented_count=ldata.get("prevented_count", 0),
                        regression_test=ldata.get("regression_test", ""),
                    )
                    self._lessons[lid] = lesson
                logger.info(f"加载 {len(self._lessons)} 条已学习教训")
            except Exception as e:
                logger.warning(f"教训加载失败: {e}")

    def _save(self):
        """保存教训到磁盘"""
        try:
            data = {}
            for lid, lesson in self._lessons.items():
                data[lid] = {
                    "error_type": lesson.error_type,
                    "error_pattern": lesson.error_pattern,
                    "context": lesson.context,
                    "root_cause": lesson.root_cause,
                    "fix_strategy": lesson.fix_strategy,
                    "severity": lesson.severity.value,
                    "occurrence_count": lesson.occurrence_count,
                    "first_seen": lesson.first_seen,
                    "last_seen": lesson.last_seen,
                    "prevented_count": lesson.prevented_count,
                    "regression_test": lesson.regression_test,
                }
            (self.data_dir / "lessons.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False)
            )
        except Exception as e:
            logger.warning(f"教训保存失败: {e}")

    # ── Pattern Extraction ─────────────────────────────

    def extract_pattern(self, error_message: str,
                       traceback: str = "") -> str:
        """从错误信息中提取通用模式"""
        # 替换具体值为占位符
        pattern = error_message

        # 替换字符串字面量
        pattern = re.sub(r"'[^']*'", "'<VALUE>'", pattern)
        pattern = re.sub(r'"[^"]*"', '"<VALUE>"', pattern)

        # 替换数字
        pattern = re.sub(r'\b\d+\b', '<NUM>', pattern)

        # 替换文件名
        pattern = re.sub(r'/[a-zA-Z0-9_/.-]+\.py', '/<PATH>.py', pattern)

        # 标准化空白
        pattern = re.sub(r'\s+', ' ', pattern).strip()

        return pattern

    def classify_error(self, error_message: str) -> Tuple[str, LessonSeverity]:
        """分类错误类型和严重程度"""
        msg = error_message.lower()

        # CRITICAL
        if any(kw in msg for kw in [
            "permission denied", "access denied", "cannot delete",
            "production", "database deleted", "rm -rf",
        ]):
            return "CriticalError", LessonSeverity.CRITICAL

        # HIGH
        if any(kw in msg for kw in [
            "modulenotfounderror", "importerror", "cannot import",
            "connection refused", "timeout", "out of memory",
        ]):
            if "modulenotfound" in msg:
                return "ModuleNotFoundError", LessonSeverity.HIGH
            if "importerror" in msg:
                return "ImportError", LessonSeverity.HIGH
            return "ConnectionError", LessonSeverity.HIGH

        # MEDIUM
        if any(kw in msg for kw in [
            "keyerror", "attributeerror", "typeerror",
            "valueerror", "indexerror",
        ]):
            if "keyerror" in msg:
                return "KeyError", LessonSeverity.MEDIUM
            if "attributeerror" in msg:
                return "AttributeError", LessonSeverity.MEDIUM
            if "typeerror" in msg:
                return "TypeError", LessonSeverity.MEDIUM
            return "ValueError", LessonSeverity.MEDIUM

        # LOW
        return "UnknownError", LessonSeverity.LOW

    # ── Learning ───────────────────────────────────────

    def learn(self, error_message: str, traceback: str = "",
             context: str = "", fix_applied: str = "") -> ErrorLesson:
        """从错误中学习"""
        # 1. 提取模式
        pattern = self.extract_pattern(error_message, traceback)

        # 2. 分类
        error_type, severity = self.classify_error(error_message)

        # 3. 计算模式哈希（去重用）
        pattern_hash = hashlib.md5(
            (error_type + pattern).encode()
        ).hexdigest()[:12]

        # 4. 检查是否已学过
        existing = None
        for lid, lesson in self._lessons.items():
            if lesson.error_type == error_type and \
               lesson.error_pattern == pattern:
                existing = lesson
                break

        if existing:
            # 更新已有教训
            existing.occurrence_count += 1
            existing.last_seen = time.time()
            if fix_applied and not existing.fix_strategy:
                existing.fix_strategy = fix_applied
            self._save()
            return existing

        # 5. 创建新教训
        lesson = ErrorLesson(
            id=f"lesson-{pattern_hash}",
            error_type=error_type,
            error_pattern=pattern,
            context=context,
            root_cause=self._infer_root_cause(error_type, error_message),
            fix_strategy=fix_applied or self._suggest_fix(error_type, error_message),
            severity=severity,
        )

        # 6. 生成回归测试
        if severity in (LessonSeverity.CRITICAL, LessonSeverity.HIGH):
            lesson.regression_test = self._generate_regression_test(lesson)

        self._lessons[lesson.id] = lesson
        self._error_history.append({
            "id": lesson.id,
            "type": error_type,
            "pattern": pattern[:200],
            "timestamp": time.time(),
        })

        self._save()
        logger.info(f"📚 学到新教训: {lesson.id} ({error_type}, {severity.value})")
        return lesson

    def _infer_root_cause(self, error_type: str,
                         message: str) -> str:
        """推断根本原因"""
        causes = {
            "KeyError": "字典访问缺少键 — 使用.get()或检查键是否存在",
            "AttributeError": "对象属性不存在 — 检查对象类型和初始化",
            "TypeError": "类型不匹配 — 检查函数参数类型",
            "ModuleNotFoundError": "缺少依赖 — pip install 或检查导入路径",
            "ImportError": "导入失败 — 检查模块名和路径",
            "ConnectionError": "网络连接失败 — 检查网络和服务状态",
            "CriticalError": "危险操作 — 已被SDB安全闸拦截",
        }
        return causes.get(error_type, "未知原因")

    def _suggest_fix(self, error_type: str, message: str) -> str:
        """建议修复策略"""
        fixes = {
            "KeyError": "将dict[key]改为dict.get(key, default)",
            "AttributeError": "添加hasattr(obj, 'attr')检查",
            "TypeError": "添加类型检查和转换",
            "ModuleNotFoundError": "pip install 缺失的包",
            "ImportError": "使用try/except导入并添加fallback",
            "ConnectionError": "添加重试逻辑和超时处理",
        }
        return fixes.get(error_type, "查看详细日志定位问题")

    def _generate_regression_test(self, lesson: ErrorLesson) -> str:
        """生成回归测试代码"""
        test_name = f"test_regression_{lesson.id.replace('-','_')}"
        return f'''def {test_name}():
    """回归: {lesson.error_type} — {lesson.root_cause}"""
    # {lesson.fix_strategy}
    # Pattern: {lesson.error_pattern[:100]}
    pass  # TODO: 补充具体断言
'''

    # ── Prediction / Prevention ────────────────────────

    def query(self, error_message: str) -> Optional[Dict]:
        """查询是否已有相关教训"""
        pattern = self.extract_pattern(error_message)
        error_type, _ = self.classify_error(error_message)

        for lid, lesson in self._lessons.items():
            if lesson.error_type == error_type and \
               self._patterns_similar(lesson.error_pattern, pattern):
                return {
                    "matched": True,
                    "lesson_id": lesson.id,
                    "error_type": lesson.error_type,
                    "root_cause": lesson.root_cause,
                    "fix_strategy": lesson.fix_strategy,
                    "severity": lesson.severity.value,
                    "occurrence_count": lesson.occurrence_count,
                    "prevented_count": lesson.prevented_count,
                }

        return {"matched": False}

    def prevent(self, error_message: str) -> bool:
        """阻止已知错误 — 返回True表示阻止了"""
        result = self.query(error_message)
        if result.get("matched"):
            lesson_id = result["lesson_id"]
            if lesson_id in self._lessons:
                self._lessons[lesson_id].prevented_count += 1
                self._prevention_log.append({
                    "lesson_id": lesson_id,
                    "error_type": result["error_type"],
                    "timestamp": time.time(),
                })
                self._save()
                return True
        return False

    def _patterns_similar(self, p1: str, p2: str) -> bool:
        """判断两个模式是否相似"""
        # 简单: 去除占位符后比较
        clean1 = p1.replace('<VALUE>', '').replace('<NUM>', '').replace('<PATH>', '')
        clean2 = p2.replace('<VALUE>', '').replace('<NUM>', '').replace('<PATH>', '')
        # Jaccard相似度 (词级)
        words1 = set(clean1.lower().split())
        words2 = set(clean2.lower().split())
        if not words1 or not words2:
            return False
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union) > 0.5

    # ── Stats ──────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取学习统计"""
        total = len(self._lessons)
        by_severity = defaultdict(int)
        by_type = defaultdict(int)
        total_prevented = 0

        for lesson in self._lessons.values():
            by_severity[lesson.severity.value] += 1
            by_type[lesson.error_type] += 1
            total_prevented += lesson.prevented_count

        # Top lessons
        top_lessons = sorted(
            self._lessons.values(),
            key=lambda l: l.occurrence_count + l.prevented_count,
            reverse=True
        )[:10]

        return {
            "total_lessons_learned": total,
            "total_errors_prevented": total_prevented,
            "prevention_rate": (
                round(total_prevented / max(1, total_prevented + sum(
                    l.occurrence_count for l in self._lessons.values()
                )), 4)
            ),
            "by_severity": dict(by_severity),
            "by_type": dict(by_type),
            "top_lessons": [
                {
                    "id": l.id,
                    "type": l.error_type,
                    "occurrences": l.occurrence_count,
                    "prevented": l.prevented_count,
                    "root_cause": l.root_cause[:100],
                }
                for l in top_lessons
            ],
            "recent_preventions": list(self._prevention_log)[-20:],
        }


# 单例
_engine: Optional[AutonomousLearningEngine] = None


def get_learning_engine() -> AutonomousLearningEngine:
    global _engine
    if _engine is None:
        _engine = AutonomousLearningEngine()
    return _engine
