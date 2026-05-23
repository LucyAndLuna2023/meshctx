"""Category Theory Agent Composer — v2.83
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
范畴论(Mac Lane, 1971)落地: Agent像函数一样组合

核心概念:
- 范畴: Agent作为对象, Pipeline作为态射
- 函子(Functor): 将一个范畴映射到另一个
- Monad: 链式操作+上下文传递 (bind/return)
- 自然变换: Agent间透明转换
"""
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

logger = logging.getLogger(__name__)

# 泛型类型
A = TypeVar('A')
B = TypeVar('B')
C = TypeVar('C')


class AgentResult(Generic[A]):
    """Agent结果 Monad — 类似Haskell的Either"""
    def __init__(self, value: Optional[A] = None, error: str = ""):
        self.value = value
        self.error = error

    @property
    def is_success(self) -> bool:
        return self.error == ""

    @property
    def is_failure(self) -> bool:
        return not self.is_success

    @staticmethod
    def success(value: A) -> 'AgentResult[A]':
        return AgentResult(value=value)

    @staticmethod
    def failure(error: str) -> 'AgentResult[A]':
        return AgentResult(error=error)

    def bind(self, f: Callable[[A], 'AgentResult[B]']) -> 'AgentResult[B]':
        """Monadic bind: 成功时继续,失败时短路"""
        if self.is_failure:
            return AgentResult(error=self.error)
        try:
            return f(self.value)
        except Exception as e:
            return AgentResult(error=str(e))

    def map(self, f: Callable[[A], B]) -> 'AgentResult[B]':
        """Functor map: 转换成功值"""
        if self.is_failure:
            return AgentResult(error=self.error)
        try:
            return AgentResult(value=f(self.value))
        except Exception as e:
            return AgentResult(error=str(e))

    def __repr__(self):
        if self.is_success:
            return f"Success({self.value})"
        return f"Failure({self.error})"


@dataclass
class AgentMorphism(Generic[A, B]):
    """Agent态射: A → B (把Agent A的输出映射到Agent B的输入)"""
    name: str
    transform: Callable[[A], B]
    cost: float = 0.0
    reversible: bool = False
    inverse: Optional[Callable[[B], A]] = None


class AgentComposer:
    """范畴论Agent组合器"""

    def __init__(self):
        self._morphisms: Dict[str, AgentMorphism] = {}
        self._composition_history: List[Dict] = []

    # ── Morphism Management ────────────────────────────

    def register_morphism(self, morph: AgentMorphism):
        """注册态射"""
        self._morphisms[morph.name] = morph

    # ── Composition ────────────────────────────────────

    def compose(self, f: AgentMorphism[A, B],
               g: AgentMorphism[B, C]) -> AgentMorphism[A, C]:
        """态射组合: f ∘ g (先f后g)"""
        def combined(x: A) -> C:
            return g.transform(f.transform(x))

        return AgentMorphism(
            name=f"{f.name}∘{g.name}",
            transform=combined,
            cost=f.cost + g.cost,
        )

    def pipeline(self, morphisms: List[AgentMorphism]) -> AgentMorphism:
        """构建Agent管道: m1 ∘ m2 ∘ ... ∘ mn"""
        if not morphisms:
            raise ValueError("管道不能为空")

        result = morphisms[0]
        for m in morphisms[1:]:
            result = self.compose(result, m)
        return result

    # ── Monadic Chain ──────────────────────────────────

    def monadic_chain(self, initial: A,
                     operations: List[Callable[[A], AgentResult[A]]]
                     ) -> AgentResult[A]:
        """Monadic链: 每一步用bind连接,失败自动短路"""
        result = AgentResult.success(initial)

        for i, op in enumerate(operations):
            result = result.bind(op)
            if result.is_failure:
                self._composition_history.append({
                    "type": "monadic_chain",
                    "step": i,
                    "status": "failed",
                    "error": result.error,
                })
                return result

        self._composition_history.append({
            "type": "monadic_chain",
            "steps": len(operations),
            "status": "success",
        })
        return result

    # ── Functor Application ────────────────────────────

    def fmap(self, morphism: AgentMorphism[A, B],
            result: AgentResult[A]) -> AgentResult[B]:
        """函子应用: 将态射应用到Result上"""
        return result.map(morphism.transform)

    # ── Natural Transformation ─────────────────────────

    def natural_transform(self,
                         morph_a: AgentMorphism[A, B],
                         morph_b: AgentMorphism[A, B],
                         input_val: A) -> Dict:
        """自然变换比较: 两个态射对同一输入的输出"""
        result_a = morph_a.transform(input_val)
        result_b = morph_b.transform(input_val)

        # 计算输出距离
        try:
            if isinstance(result_a, (int, float)) and isinstance(result_b, (int, float)):
                distance = abs(float(result_a) - float(result_b))
            elif isinstance(result_a, str) and isinstance(result_b, str):
                # 字符串相似度
                words_a = set(str(result_a).lower().split())
                words_b = set(str(result_b).lower().split())
                union = words_a | words_b
                inter = words_a & words_b
                distance = 1.0 - len(inter) / max(1, len(union))
            else:
                distance = 0.5  # 无法比较
        except Exception:
            distance = 0.5

        return {
            "input": str(input_val)[:100],
            "output_a": str(result_a)[:100],
            "output_b": str(result_b)[:100],
            "distance": round(distance, 3),
            "equivalent": distance < 0.1,
        }

    # ── Pre-built Morphisms ────────────────────────────

    def create_text_morphisms(self) -> List[AgentMorphism]:
        """创建常用文本处理态射"""
        morphs = []

        # strip → lowercase
        morphs.append(AgentMorphism[str, str](
            name="sanitize",
            transform=lambda s: s.strip().lower(),
            cost=0.01,
        ))

        # extract first N chars
        morphs.append(AgentMorphism[str, str](
            name="truncate_100",
            transform=lambda s: s[:100],
            cost=0.005,
        ))

        # JSON parse
        import json
        morphs.append(AgentMorphism[str, dict](
            name="json_parse",
            transform=lambda s: json.loads(s) if s else {},
            cost=0.05,
        ))

        # Hash
        import hashlib
        morphs.append(AgentMorphism[str, str](
            name="sha256",
            transform=lambda s: hashlib.sha256(s.encode()).hexdigest()[:16],
            cost=0.02,
        ))

        return morphs

    # ── Stats ──────────────────────────────────────────

    def get_category_stats(self) -> Dict:
        return {
            "objects": len(set(m.name.split("∘")[0] for m in self._morphisms.values())),
            "morphisms": len(self._morphisms),
            "compositions": len(self._composition_history),
            "identity_exists": any(
                m.reversible for m in self._morphisms.values()
            ),
            "commutative_diagrams": len(self._composition_history),
        }

    def get_stats(self) -> Dict:
        return self.get_category_stats()


# 单例
_composer: Optional[AgentComposer] = None


def get_agent_composer() -> AgentComposer:
    global _composer
    if _composer is None:
        _composer = AgentComposer()
    return _composer
