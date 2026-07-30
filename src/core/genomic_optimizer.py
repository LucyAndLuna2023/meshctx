"""
meshctx GenomicOptimizer — 基因组学启发的 Agent 进化引擎

核心理念映射:
  - Agent 配置参数 = 基因型 (genotype)
  - Agent 运行表现 = 表现型 (phenotype)
  - 任务成功率 = 适应度 (fitness)
  - 参数变异 = 点突变 + 重组
  - Top-K 精英保留 = 自然选择
  - 多样性保护 = 生态位隔离

零外部依赖 — Python stdlib only.

线程安全 — 所有变异操作使用 copy-deep-mutate 模式。
"""
from __future__ import annotations

import copy
import json
import logging
import math
import os
import random
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.genomic")


# ═══════════════════════════════════════════════════════════════
# 基因组配置 — 可调参数空间
# ═══════════════════════════════════════════════════════════════

@dataclass
class Genome:
    """一个 Agent 的完整参数基因组。
    
    每个字段:
      value: 当前值
      mutate_range: 变异范围 (min, max) 或离散候选集
      mutate_rate: 每代变异概率 (0-1)
      mutate_sigma: 连续参数的高斯变异标准差
    """
    temperature: float = 0.7
    temperature_range: Tuple[float, float] = (0.1, 1.5)
    temperature_sigma: float = 0.1

    top_p: float = 0.9
    top_p_range: Tuple[float, float] = (0.5, 1.0)
    top_p_sigma: float = 0.05

    max_tokens: int = 4096
    max_tokens_range: Tuple[int, int] = (512, 16384)
    max_tokens_sigma: float = 1024.0

    system_prompt_style: str = "concise"
    prompt_styles: Tuple[str, ...] = (
        "concise", "detailed", "step_by_step", "creative",
        "analytical", "minimal", "encouraging", "direct",
    )

    memory_weight: float = 0.6
    memory_weight_range: Tuple[float, float] = (0.1, 1.0)
    memory_weight_sigma: float = 0.1

    retrieval_top_k: int = 5
    retrieval_top_k_range: Tuple[int, int] = (1, 20)
    retrieval_top_k_sigma: float = 2.0

    # ── 元信息 ──
    generation: int = 0
    parent_id: str = ""
    mutation_count: int = 0
    fitness_history: List[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "system_prompt_style": self.system_prompt_style,
            "memory_weight": self.memory_weight,
            "retrieval_top_k": self.retrieval_top_k,
            "generation": self.generation,
            "parent_id": self.parent_id,
            "mutation_count": self.mutation_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Genome:
        g = cls()
        for k, v in d.items():
            if hasattr(g, k):
                setattr(g, k, v)
        return g

    def clone(self) -> Genome:
        """深度克隆，避免共享引用。"""
        return copy.deepcopy(self)


# ═══════════════════════════════════════════════════════════════
# 变异算子 — 模拟点突变 + 重组
# ═══════════════════════════════════════════════════════════════
class MutationEngine:
    """变异引擎 — 对标 DNA 聚合酶错误 + 减数分裂重组。

    实现三种变异:
      1. 点突变: 单个参数高斯扰动
      2. 大跳突变: 参数完全重采样（模拟转座子跳跃）
      3. 交叉重组: 两个父代的参数混合
    """

    def __init__(self, mutation_strength: float = 1.0, seed: int = None):
        self.strength = mutation_strength
        self.rng = random.Random(seed or int(time.time() * 1000))

    def point_mutate(self, genome: Genome) -> Genome:
        """点突变 — 每个参数独立按概率变异。"""
        mutant = genome.clone()
        mutant.generation += 1
        mutant.parent_id = hex(id(genome) & 0xFFFFFFFF)[2:]
        mutant.mutation_count = 0

        # temperature
        if self.rng.random() < 0.3 * self.strength:
            noise = self.rng.gauss(0, genome.temperature_sigma * self.strength)
            mutant.temperature = self._clamp(
                mutant.temperature + noise, *genome.temperature_range
            )
            mutant.mutation_count += 1

        # top_p
        if self.rng.random() < 0.3 * self.strength:
            noise = self.rng.gauss(0, genome.top_p_sigma * self.strength)
            mutant.top_p = self._clamp(
                mutant.top_p + noise, *genome.top_p_range
            )
            mutant.mutation_count += 1

        # max_tokens
        if self.rng.random() < 0.2 * self.strength:
            noise = self.rng.gauss(0, genome.max_tokens_sigma * self.strength)
            mutant.max_tokens = int(self._clamp(
                mutant.max_tokens + noise, *genome.max_tokens_range
            ))
            mutant.mutation_count += 1

        # system_prompt_style — 离散跳跃（类似转座子插入）
        if self.rng.random() < 0.15 * self.strength:
            current = mutant.system_prompt_style
            choices = [s for s in genome.prompt_styles if s != current]
            if choices:
                mutant.system_prompt_style = self.rng.choice(choices)
                mutant.mutation_count += 1

        # memory_weight
        if self.rng.random() < 0.3 * self.strength:
            noise = self.rng.gauss(0, genome.memory_weight_sigma * self.strength)
            mutant.memory_weight = self._clamp(
                mutant.memory_weight + noise, *genome.memory_weight_range
            )
            mutant.mutation_count += 1

        # retrieval_top_k
        if self.rng.random() < 0.2 * self.strength:
            noise = self.rng.gauss(0, genome.retrieval_top_k_sigma * self.strength)
            mutant.retrieval_top_k = int(self._clamp(
                mutant.retrieval_top_k + noise, *genome.retrieval_top_k_range
            ))
            mutant.mutation_count += 1

        return mutant

    def jump_mutate(self, genome: Genome) -> Genome:
        """大跳突变 — 随机重置部分参数（转座子式跳跃）。"""
        mutant = genome.clone()
        mutant.generation += 1
        mutant.parent_id = "jump_" + hex(id(genome) & 0xFFFFFFFF)[2:]
        mutant.mutation_count = 0

        # 随机选 2-3 个参数完全重置
        params_to_reset = self.rng.sample(
            ["temperature", "top_p", "memory_weight", "system_prompt_style"],
            k=self.rng.randint(2, 3),
        )

        if "temperature" in params_to_reset:
            lo, hi = genome.temperature_range
            mutant.temperature = self.rng.uniform(lo, hi)
            mutant.mutation_count += 1

        if "top_p" in params_to_reset:
            lo, hi = genome.top_p_range
            mutant.top_p = self.rng.uniform(lo, hi)
            mutant.mutation_count += 1

        if "memory_weight" in params_to_reset:
            lo, hi = genome.memory_weight_range
            mutant.memory_weight = self.rng.uniform(lo, hi)
            mutant.mutation_count += 1

        if "system_prompt_style" in params_to_reset:
            mutant.system_prompt_style = self.rng.choice(genome.prompt_styles)
            mutant.mutation_count += 1

        return mutant

    def crossover(self, parent_a: Genome, parent_b: Genome) -> Genome:
        """交叉重组 — 两种父代参数按位混合（模拟减数分裂）。"""
        child = Genome()
        child.generation = max(parent_a.generation, parent_b.generation) + 1
        child.parent_id = "cross"

        # 每个参数 50%概率来自父A，50%来自父B
        if self.rng.random() < 0.5:
            child.temperature = parent_a.temperature
        else:
            child.temperature = parent_b.temperature

        if self.rng.random() < 0.5:
            child.top_p = parent_a.top_p
        else:
            child.top_p = parent_b.top_p

        if self.rng.random() < 0.5:
            child.max_tokens = parent_a.max_tokens
        else:
            child.max_tokens = parent_b.max_tokens

        if self.rng.random() < 0.5:
            child.system_prompt_style = parent_a.system_prompt_style
        else:
            child.system_prompt_style = parent_b.system_prompt_style

        if self.rng.random() < 0.5:
            child.memory_weight = parent_a.memory_weight
        else:
            child.memory_weight = parent_b.memory_weight

        if self.rng.random() < 0.5:
            child.retrieval_top_k = parent_a.retrieval_top_k
        else:
            child.retrieval_top_k = parent_b.retrieval_top_k

        return child

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))


# ═══════════════════════════════════════════════════════════════
# 适应度评估器
# ═══════════════════════════════════════════════════════════════

class FitnessEvaluator:
    """适应度评估 — 基于任务反馈打分。

    多维度评分:
      - success_rate: 任务完成率 (0-1)
      - latency: 响应延迟 (越低越好)
      - token_efficiency: token使用效率
      - user_rating: 用户评分 (隐式信号)
    """

    def __init__(self):
        self._feedback: Dict[str, List[Dict]] = defaultdict(list)
        self._lock = threading.Lock()

    def record_feedback(
        self,
        genome_id: str,
        success: bool,
        latency_ms: float = 0,
        tokens_used: int = 0,
        user_accepted: bool = True,
    ):
        """记录一次任务反馈。"""
        with self._lock:
            self._feedback[genome_id].append({
                "success": success,
                "latency_ms": latency_ms,
                "tokens_used": tokens_used,
                "user_accepted": user_accepted,
                "timestamp": time.time(),
            })
            # 限制历史长度（滑动窗口，模拟免疫记忆衰减）
            if len(self._feedback[genome_id]) > 100:
                self._feedback[genome_id] = self._feedback[genome_id][-100:]

    def evaluate(self, genome_id: str) -> float:
        """计算适应度分数 (0-1)。

        权重分配:
          - 任务成功 40%
          - 延迟 20%
          - Token效率 20%
          - 用户接受 20%
        """
        with self._lock:
            history = self._feedback.get(genome_id, [])

        if not history:
            return 0.5  # 无数据 → 中性值

        n = len(history)

        # 成功率
        success_rate = sum(1 for h in history if h["success"]) / n

        # 延迟（归一化：低于2000ms满分，8000ms以上0分）
        latencies = [h["latency_ms"] for h in history if h["latency_ms"] > 0]
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            latency_score = max(0, 1.0 - (avg_latency - 2000) / 6000)
        else:
            latency_score = 0.5

        # Token 效率（越低越好，按 500/query 满分，5000/query 0分）
        tokens = [h["tokens_used"] for h in history if h["tokens_used"] > 0]
        if tokens:
            avg_tokens = sum(tokens) / len(tokens)
            token_score = max(0, 1.0 - (avg_tokens - 500) / 4500)
        else:
            token_score = 0.5

        # 用户接受率
        accept_rate = sum(1 for h in history if h.get("user_accepted", True)) / n

        return (
            0.40 * success_rate
            + 0.20 * latency_score
            + 0.20 * token_score
            + 0.20 * accept_rate
        )

    def top_performers(self, genome_ids: List[str], k: int = 3) -> List[str]:
        """返回适应度最高的 K 个基因组ID。"""
        scored = [(gid, self.evaluate(gid)) for gid in genome_ids]
        scored.sort(key=lambda x: -x[1])
        return [gid for gid, _ in scored[:k]]

    def stats(self) -> dict:
        with self._lock:
            return {
                "total_genomes": len(self._feedback),
                "total_feedback": sum(len(v) for v in self._feedback.values()),
            }


# ═══════════════════════════════════════════════════════════════
# 生态位多样性保护
# ═══════════════════════════════════════════════════════════════

class NichePreserver:
    """生态位保护 — 防止种群过早收敛到单一最优解。

    原理（类比 MHC 多样性）:
      - 把参数空间分区成"生态位"
      - 每个生态位保留至少一个个体
      - 选择时惩罚密集生态位
    """

    def __init__(self, niche_bins: int = 5):
        self.niche_bins = niche_bins

    def niche_id(self, genome: Genome) -> int:
        """把基因组映射到生态位编号。"""
        # 基于 temperature + memory_weight 做 2D 分区
        t_bin = int(genome.temperature * self.niche_bins / 2.0)
        m_bin = int(genome.memory_weight * self.niche_bins)
        return (t_bin * self.niche_bins + m_bin) % (self.niche_bins ** 2)

    def diversity_score(self, population: List[Genome]) -> float:
        """计算种群多样性 (0-1)。1 = 完全均匀分布。"""
        if not population:
            return 0.0
        counts = defaultdict(int)
        for g in population:
            counts[self.niche_id(g)] += 1
        # 用熵的倒数作为多样性指标
        total = len(population)
        entropy = -sum(
            (c / total) * math.log(c / total + 1e-10)
            for c in counts.values()
        )
        max_entropy = math.log(min(len(counts), self.niche_bins ** 2) + 1)
        return entropy / (max_entropy + 1e-10)

    def select_diverse(
        self, population: List[Genome], scores: List[float], k: int
    ) -> List[Genome]:
        """生态位感知选择: 高适应度 + 低生态位拥挤度。"""
        niche_counts = defaultdict(int)
        selected = []
        scored = list(zip(population, scores))
        scored.sort(key=lambda x: -x[1])

        for genome, score in scored:
            if len(selected) >= k:
                break
            niche = self.niche_id(genome)
            penalty = niche_counts[niche] * 0.1  # 每多一个同生态位个体扣0.1
            adjusted = score - penalty
            if adjusted > 0.3 or niche_counts[niche] == 0:  # 精英豁免
                selected.append(genome)
                niche_counts[niche] += 1

        return selected


# ═══════════════════════════════════════════════════════════════
# 进化主循环 — 对标自然选择 + 遗传漂变
# ═══════════════════════════════════════════════════════════════

class GenomicOptimizer:
    """基因组学启发的进化优化器。

    流程:
      1. 初始化种群 (N 个随机基因组)
      2. 每代:
         a. 记录适应度反馈
         b. 精英保留 (Top 20%)
         c. 交叉重组 (40%)
         d. 点突变 (30%)
         e. 大跳突变 (10% — 防止陷入局部最优)
         f. 生态位选择 — 保证多样性
      3. 持久化最优基因组
    """

    DATA_DIR = Path.home() / ".meshctx" / "genomes"

    def __init__(
        self,
        population_size: int = 20,
        elite_ratio: float = 0.2,
        jump_rate: float = 0.1,
    ):
        self.population_size = population_size
        self.elite_ratio = elite_ratio
        self.jump_rate = jump_rate

        self.mutator = MutationEngine()
        self.evaluator = FitnessEvaluator()
        self.niche = NichePreserver()

        self._population: List[Genome] = []
        self._generation: int = 0
        self._best: Optional[Genome] = None
        self._best_score: float = 0.0
        self._lock = threading.Lock()

        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ── 初始化 ──

    def initialize(self):
        """创建初始种群 — 随机基因组（模拟始祖种群）。"""
        with self._lock:
            self._population = [self._random_genome() for _ in range(self.population_size)]
            self._generation = 0
            logger.info(
                f"GenomicOptimizer initialized: pop={self.population_size}"
            )

    def _random_genome(self) -> Genome:
        g = Genome()
        g.temperature = random.uniform(*g.temperature_range)
        g.top_p = random.uniform(*g.top_p_range)
        g.max_tokens = random.randint(*g.max_tokens_range)
        g.system_prompt_style = random.choice(g.prompt_styles)
        g.memory_weight = random.uniform(*g.memory_weight_range)
        g.retrieval_top_k = random.randint(*g.retrieval_top_k_range)
        return g
    # ── 反馈接口 ──

    def record(
        self,
        genome: Genome,
        success: bool,
        latency_ms: float = 0,
        tokens_used: int = 0,
        user_accepted: bool = True,
    ):
        """记录一个基因组的任务反馈。"""
        gid = self._genome_id(genome)
        self.evaluator.record_feedback(gid, success, latency_ms, tokens_used, user_accepted)

    # ── 进化步骤 ──

    def evolve(self, steps: int = 1) -> Genome:
        """执行 N 代进化，返回当前最优基因组。"""
        with self._lock:
            for _ in range(steps):
                self._evolve_one_generation()
            self._generation += steps
            self._persist_best()
            return self._best

    def _evolve_one_generation(self):
        """一代进化。"""
        pop = self._population
        # 评估适应度
        gids = [self._genome_id(g) for g in pop]
        scores = [self.evaluator.evaluate(gid) for gid in gids]

        # 记录最优
        best_idx = max(range(len(scores)), key=lambda i: scores[i])
        if scores[best_idx] > self._best_score:
            self._best = pop[best_idx].clone()
            self._best_score = scores[best_idx]
            self._best.generation = self._generation

        # 精英数量
        n_elite = max(1, int(self.population_size * self.elite_ratio))
        n_jump = max(1, int(self.population_size * self.jump_rate))
        n_cross = self.population_size - n_elite - n_jump - n_jump

        next_gen = []

        # 1. 精英保留（适应度选择）
        elite = self.niche.select_diverse(pop, scores, n_elite)
        next_gen.extend([e.clone() for e in elite])

        # 2. 交叉重组
        for _ in range(max(0, n_cross)):
            a = self._tournament_select(pop, scores, 3)
            b = self._tournament_select(pop, scores, 3)
            child = self.mutator.crossover(a, b)
            child = self.mutator.point_mutate(child)  # 轻度突变
            next_gen.append(child)

        # 3. 点突变
        for _ in range(n_jump):
            parent = self._tournament_select(pop, scores, 3)
            mutant = self.mutator.point_mutate(parent)
            next_gen.append(mutant)

        # 4. 大跳突变 — 维持多样性，防止早熟收敛
        for _ in range(n_jump):
            parent = random.choice(pop)
            mutant = self.mutator.jump_mutate(parent)
            next_gen.append(mutant)

        # 填充到目标大小
        while len(next_gen) < self.population_size:
            next_gen.append(self._random_genome())

        self._population = next_gen[: self.population_size]

    def _tournament_select(
        self, pop: List[Genome], scores: List[float], k: int = 3
    ) -> Genome:
        """锦标赛选择 — 随机选 K 个，返回分最高的。"""
        indices = random.sample(range(len(pop)), min(k, len(pop)))
        best = max(indices, key=lambda i: scores[i])
        return pop[best]

    # ── 当前最优 ──

    @property
    def best_genome(self) -> Optional[Genome]:
        return self._best

    @property
    def generation(self) -> int:
        return self._generation

    def get_active_genome(self) -> Genome:
        """获取当前生效的基因组 — 最新一代的最优个体，或默认。"""
        if self._best:
            return self._best
        return Genome()

    # ── 持久化 ──

    def _genome_id(self, genome: Genome) -> str:
        """基因组指纹 — 基于参数哈希。"""
        import hashlib
        raw = f"t{genome.temperature:.3f}_p{genome.top_p:.3f}_tk{genome.max_tokens}_s{genome.system_prompt_style}_mw{genome.memory_weight:.3f}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def _persist_best(self):
        """持久化最优基因组到磁盘。"""
        if not self._best:
            return
        fpath = self.DATA_DIR / "best_genome.json"
        data = self._best.to_dict()
        data["fitness_score"] = self._best_score
        data["generation"] = self._generation
        data["timestamp"] = time.time()
        try:
            fpath.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"Failed to persist best genome: {e}")

    def load_best(self) -> Optional[Genome]:
        """从磁盘加载最优基因组。"""
        fpath = self.DATA_DIR / "best_genome.json"
        if not fpath.exists():
            return None
        try:
            data = json.loads(fpath.read_text())
            g = Genome.from_dict(data)
            self._best = g
            self._best_score = data.get("fitness_score", 0.5)
            self._generation = data.get("generation", 0)
            logger.info(f"Loaded best genome (gen={self._generation}, score={self._best_score:.3f})")
            return g
        except Exception as e:
            logger.warning(f"Failed to load best genome: {e}")
            return None

    # ── 统计 ──

    def stats(self) -> dict:
        return {
            "generation": self._generation,
            "population_size": len(self._population),
            "best_score": self._best_score,
            "best_genome": self._best.to_dict() if self._best else None,
            "diversity": self.niche.diversity_score(self._population),
            "feedback": self.evaluator.stats(),
        }


# ═══════════════════════════════════════════════════════════════
# Agent 集成 — 配置驱动的基因组应用
# ═══════════════════════════════════════════════════════════════

class AgentGenomeBridge:
    """连接进化优化器和 Agent 运行循环。

    用法:
      bridge = AgentGenomeBridge(optimizer)
      genome = bridge.get_active_genome()
      # 用 genome 参数运行一次任务...
      bridge.record_task(success=True, latency_ms=1234, tokens_used=800)
      # 积累足够反馈后进化
      bridge.evolve_if_ready(min_feedback=5)
    """

    def __init__(self, optimizer: GenomicOptimizer):
        self.optimizer = optimizer
        self._current_genome: Optional[Genome] = None
        self._feedback_count: int = 0
        self._evolution_lock = threading.Lock()

    def get_active_genome(self) -> Genome:
        """获取当前生效的基因组配置。"""
        if self._current_genome is None:
            self._current_genome = self.optimizer.get_active_genome()
        return self._current_genome

    def record_task(
        self,
        success: bool,
        latency_ms: float = 0,
        tokens_used: int = 0,
        user_accepted: bool = True,
    ):
        """记录任务结果。"""
        if self._current_genome:
            self.optimizer.record(
                self._current_genome,
                success=success,
                latency_ms=latency_ms,
                tokens_used=tokens_used,
                user_accepted=user_accepted,
            )
            self._feedback_count += 1

    def evolve_if_ready(self, min_feedback: int = 5):
        """如果积累了足够反馈，触发一代进化。"""
        if self._feedback_count >= min_feedback:
            with self._evolution_lock:
                new_genome = self.optimizer.evolve(steps=1)
                self._current_genome = new_genome
                self._feedback_count = 0
                logger.info(
                    f"Genome evolved: gen={self.optimizer.generation}, "
                    f"score={self.optimizer._best_score:.3f}"
                )

    def stats(self) -> dict:
        return self.optimizer.stats()


# ═══════════════════════════════════════════════════════════════
# Kernel Plugin
# ═══════════════════════════════════════════════════════════════

class GenomicOptimizerPlugin:
    """基因组优化器插件 — 挂载到 meshctx 内核。"""

    info = type("Info", (), {
        "name": "genomic_optimizer",
        "version": "1.0.0",
        "dependencies": [],
        "category": "optimization",
        "description": "Genomics-inspired evolutionary Agent optimizer: mutation + selection + niche preservation",
    })()

    state: str = "loaded"

    def __init__(self, population_size: int = 20):
        self.optimizer = GenomicOptimizer(population_size=population_size)
        self.bridge: Optional[AgentGenomeBridge] = None
        self._started = False

    async def on_load(self, kernel) -> bool:
        """加载插件 — 初始化种群并加载已有最优解。"""
        try:
            loaded = self.optimizer.load_best()
            if not loaded:
                self.optimizer.initialize()
            else:
                # 从已有最优解重建种群
                self.optimizer.initialize()
                self.optimizer._best = loaded
            self.bridge = AgentGenomeBridge(self.optimizer)
            self.state = "active"
            self._started = True
            logger.info(
                f"GenomicOptimizerPlugin loaded: gen={self.optimizer.generation}, "
                f"best_score={self.optimizer._best_score:.3f}, "
                f"pop={self.optimizer.population_size}"
            )
            return True
        except Exception as e:
            logger.error(f"GenomicOptimizerPlugin failed to load: {e}")
            self.state = "error"
            return False

    async def on_event(self, event):
        """监听任务完成事件 → 记录反馈。"""
        if event.type == "agent.task.completed" and self.bridge:
            data = event.data or {}
            self.bridge.record_task(
                success=data.get("success", True),
                latency_ms=data.get("latency_ms", 0),
                tokens_used=data.get("tokens_used", 0),
                user_accepted=data.get("user_accepted", True),
            )
            # 每 10 个反馈进化一次
            self.bridge.evolve_if_ready(min_feedback=10)
        return True

    def generate_report(self) -> dict:
        return {
            "name": "genomic_optimizer",
            "state": self.state,
            **self.optimizer.stats(),
        }

    async def on_unload(self):
        self._started = False
        self.optimizer._persist_best()
        logger.info("GenomicOptimizerPlugin unloaded")


# ═══════════════════════════════════════════════════════════════
# 便捷 API
# ═══════════════════════════════════════════════════════════════

_genomic_optimizer: Optional[GenomicOptimizer] = None


def get_genomic_optimizer() -> GenomicOptimizer:
    """获取全局基因组优化器单例。"""
    global _genomic_optimizer
    if _genomic_optimizer is None:
        _genomic_optimizer = GenomicOptimizer()
        _genomic_optimizer.load_best()
        if not _genomic_optimizer._best:
            _genomic_optimizer.initialize()
    return _genomic_optimizer
