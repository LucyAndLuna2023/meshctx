"""v2.83 Category Composer — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def composer():
    from src.core.category_composer import AgentComposer, AgentMorphism, AgentResult
    c = AgentComposer()

    # Register basic morphisms
    c.register_morphism(AgentMorphism[str, str](
        name="uppercase",
        transform=lambda s: s.upper(),
        cost=0.01,
    ))
    c.register_morphism(AgentMorphism[str, int](
        name="length",
        transform=lambda s: len(s),
        cost=0.005,
    ))
    c.register_morphism(AgentMorphism[str, str](
        name="reverse",
        transform=lambda s: s[::-1],
        cost=0.02,
        reversible=True,
        inverse=lambda s: s[::-1],
    ))
    return c


class TestAgentResult:
    def test_success(self):
        from src.core.category_composer import AgentResult
        r = AgentResult.success(42)
        assert r.is_success is True
        assert r.value == 42

    def test_failure(self):
        from src.core.category_composer import AgentResult
        r = AgentResult.failure("something broke")
        assert r.is_failure is True
        assert r.error == "something broke"

    def test_bind_success(self):
        from src.core.category_composer import AgentResult
        r = AgentResult.success(5).bind(lambda x: AgentResult.success(x * 2))
        assert r.value == 10

    def test_bind_failure_short_circuits(self):
        from src.core.category_composer import AgentResult
        r = AgentResult.failure("error").bind(lambda x: AgentResult.success(x))
        assert r.is_failure is True

    def test_map(self):
        from src.core.category_composer import AgentResult
        r = AgentResult.success("hello").map(lambda s: s.upper())
        assert r.value == "HELLO"

    def test_map_preserves_failure(self):
        from src.core.category_composer import AgentResult
        r = AgentResult.failure("err").map(lambda x: x)
        assert r.is_failure is True


class TestComposition:
    def test_compose(self, composer):
        from src.core.category_composer import AgentMorphism
        f = composer._morphisms["uppercase"]
        g = composer._morphisms["length"]
        h = composer.compose(f, g)  # uppercase → length
        result = h.transform("hello")
        assert result == 5  # "HELLO" length = 5

    def test_pipeline(self, composer):
        from src.core.category_composer import AgentMorphism
        # uppercase → reverse → length
        f = composer._morphisms["uppercase"]
        r = composer._morphisms["reverse"]
        l = composer._morphisms["length"]
        pipeline = composer.pipeline([f, r, l])
        result = pipeline.transform("hello")
        assert result == 5  # OLLEH length = 5

    def test_composition_cost(self, composer):
        f = composer._morphisms["uppercase"]
        g = composer._morphisms["length"]
        h = composer.compose(f, g)
        assert h.cost == f.cost + g.cost


class TestMonadicChain:
    def test_monadic_chain_success(self, composer):
        from src.core.category_composer import AgentResult
        ops = [
            lambda x: AgentResult.success(x * 2),
            lambda x: AgentResult.success(x + 10),
        ]
        result = composer.monadic_chain(5, ops)
        assert result.is_success is True
        assert result.value == 20  # (5*2) + 10

    def test_monadic_chain_short_circuit(self, composer):
        from src.core.category_composer import AgentResult
        ops = [
            lambda x: AgentResult.success(x * 2),
            lambda x: AgentResult.failure("broke at step 2"),
            lambda x: AgentResult.success(x + 100),
        ]
        result = composer.monadic_chain(5, ops)
        assert result.is_failure is True
        assert "broke" in result.error


class TestNaturalTransformation:
    def test_natural_transform(self, composer):
        r = composer.natural_transform(
            composer._morphisms["uppercase"],
            composer._morphisms["reverse"],
            "hello",
        )
        assert "output_a" in r
        assert r["output_a"] == "HELLO"
        assert r["output_b"] == "olleh"


class TestPrebuiltMorphisms:
    def test_create_text_morphisms(self, composer):
        morphs = composer.create_text_morphisms()
        assert len(morphs) >= 3


class TestStats:
    def test_category_stats(self, composer):
        stats = composer.get_category_stats()
        assert stats["morphisms"] >= 3
