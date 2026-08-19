# -*- coding: utf-8 -*-
"""CMA-ES 优化器验收测试（phase-1）

覆盖:
  A. 简单二次函数收敛到全局最优（spherical landscape）
  B. bounds 约束生效
  C. 有参数相关性的鞍面仍能收敛（CMA 协方差自适应价值）
  D. GenomicOptimizer.optimize_with_cmaes 接口集成
"""
import math

import pytest


class TestCmaesConvergence:
    def test_converges_on_sphere(self):
        """f(x) = -(x0^2 + x1^2)，最优应在 (0,0)。"""
        from src.core.cmaes_optimizer import CmaesOptimizer
        opt = CmaesOptimizer(dim=2, bounds=[(-5, 5), (-5, 5)], seed=42)
        result = opt.run(lambda x: -(x[0] ** 2 + x[1] ** 2), iters=60)
        assert result.best_fitness > -0.01, (
            f"应收敛到接近 0，实际 {result.best_fitness:.5f}"
        )
        assert abs(result.best_x[0]) < 0.05 and abs(result.best_x[1]) < 0.05

    def test_bounds_respected(self):
        from src.core.cmaes_optimizer import CmaesOptimizer
        # 最优在界外时结果必须被 clamp 回边界
        opt = CmaesOptimizer(dim=1, bounds=[(0.1, 1.0)], seed=7)
        result = opt.run(lambda x: -((x[0] - 5.0) ** 2), iters=40)
        assert 0.1 <= result.best_x[0] <= 1.0
        assert result.best_x[0] == pytest.approx(1.0, abs=1e-3)

    def test_correlated_ridge_converges(self):
        """目标在 x0≈x1 的脊线上：CMA 协方差自适应应优于各向同性采样。"""
        from src.core.cmaes_optimizer import CmaesOptimizer
        opt = CmaesOptimizer(dim=2, bounds=[(-3, 3), (-3, 3)], seed=11)
        # 最优在 (1.0, 1.0)
        result = opt.run(
            lambda x: -((x[0] - 1.0) ** 2 + (x[1] - 1.0) ** 2 + 0.5 * (x[0] - x[1]) ** 2),
            iters=80,
        )
        assert result.best_fitness > -0.05
        assert abs(result.best_x[0] - 1.0) < 0.1
        assert abs(result.best_x[1] - 1.0) < 0.1

    def test_history_monotonic_best(self):
        from src.core.cmaes_optimizer import CmaesOptimizer
        opt = CmaesOptimizer(dim=1, bounds=[(-2, 2)], seed=3)
        result = opt.run(lambda x: -(x[0] ** 2), iters=30)
        assert len(result.history) == 30
        # history 记录的是历代 best，应非严格递增
        assert all(result.history[i] <= result.history[i + 1] + 1e-9 for i in range(len(result.history) - 1))


class TestCmaesGenomicIntegration:
    def test_optimize_with_cmaes_interface(self):
        """GenomicOptimizer.optimize_with_cmaes 应返回更新后的最优 Genome。"""
        from src.core.genomic_optimizer import GenomicOptimizer

        opt = GenomicOptimizer(population_size=8)
        opt.initialize()

        def fitness_fn(g):
            # 越靠近 memory_weight=0.8、top_p=0.7 分越高
            return -(g.memory_weight - 0.8) ** 2 - (g.top_p - 0.7) ** 2 * 0.5

        best = opt.optimize_with_cmaes(fitness_fn, iters=30)
        assert best is not None
        assert 0.1 <= best.memory_weight <= 1.0
        assert abs(best.memory_weight - 0.8) < 0.15, (
            f"CMA-ES 应把 memory_weight 推向 0.8，实际 {best.memory_weight:.3f}"
        )
        assert opt._best_score is not None and opt._best_score > -0.1

    def test_cmaes_persists_best(self, tmp_path, monkeypatch):
        """CMA-ES 最优应持久化到 best_genome.json。"""
        from src.core.genomic_optimizer import GenomicOptimizer
        monkeypatch.setattr(GenomicOptimizer, "DATA_DIR", tmp_path)
        opt = GenomicOptimizer(population_size=6)
        opt.initialize()
        opt.optimize_with_cmaes(lambda g: -(g.temperature - 0.9) ** 2, iters=20)
        f = tmp_path / "best_genome.json"
        assert f.exists(), "CMA-ES 结束后应持久化最优基因组"
        import json
        data = json.loads(f.read_text())
        assert "memory_weight" in data
        assert data["fitness_score"] > -0.1
