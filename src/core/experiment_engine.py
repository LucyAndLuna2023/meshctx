"""
meshctx Experiment Engine — 实验引擎 v1.0
==========================================

生产级 A/B 测试和在线实验引擎,
支持多臂 bandit、固定流量分配、统计显著性检验。

核心能力:
  1. 多臂老虎机 (Thompson Sampling, Epsilon-Greedy)
  2. 固定比例 A/B/N 测试
  3. 统计显著性检验 (Chi-squared, Z-test)
  4. 实验生命周期管理
  5. 自动优胜者选择

使用场景:
  - A/B 测试 UI 变体
  - 多臂 bandit 优化推荐策略
  - 模型评估 (对比新旧模型)
  - 内容优化实验

使用示例:
  engine = get_experiment_engine()
  exp = engine.create_experiment("cta_button_test", variants=["green", "blue", "red"])
  variant = engine.assign("cta_button_test", user_id="user123")
  engine.record_result("cta_button_test", user_id="user123", metric="click", value=1.0)

代码量: ~450 行
"""

import hashlib
import json
import logging
import math
import os
import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("meshctx.experiment_engine")


# ═══════════════════════════════════════════════════════════
# 常量和枚举
# ═══════════════════════════════════════════════════════════

class ExperimentType(str, Enum):
    """实验类型"""
    AB_TEST = "ab_test"               # 经典 A/B/N 测试
    MULTI_ARM_BANDIT = "multi_arm_bandit"  # 多臂老虎机
    INTERLEAVING = "interleaving"     # 交错实验


class ExperimentState(str, Enum):
    """实验生命周期"""
    DRAFT = "draft"             # 草稿
    RUNNING = "running"         # 运行中
    PAUSED = "paused"           # 暂停
    COMPLETED = "completed"     # 已完成
    ARCHIVED = "archived"       # 已归档


class BanditAlgorithm(str, Enum):
    """Bandit 算法"""
    THOMPSON_SAMPLING = "thompson_sampling"   # 汤普森采样
    EPSILON_GREEDY = "epsilon_greedy"          # Epsilon-贪婪
    UCB = "ucb"                                 # 上置信界


class SignificanceLevel(str, Enum):
    """显著性水平"""
    P90 = "0.10"
    P95 = "0.05"
    P99 = "0.01"
    P999 = "0.001"


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class VariantStats:
    """变体统计"""
    name: str
    impressions: int = 0             # 展示次数 (分配)
    successes: int = 0               # 成功次数 (e.g. 点击)
    trials: int = 0                  # 试验次数
    total_value: float = 0.0         # 累计值 (连续指标)
    values: List[float] = field(default_factory=list)  # 最近值 (环形)
    created_at: float = field(default_factory=time.time)

    @property
    def conversion_rate(self, **kw) -> float:
        """转化率"""
        if self.trials == 0:
            return 0.0
        return self.successes / self.trials

    @property
    def mean_value(self, **kw) -> float:
        """平均值"""
        if self.trials == 0:
            return 0.0
        return self.total_value / self.trials

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "name": self.name,
            "impressions": self.impressions,
            "successes": self.successes,
            "trials": self.trials,
            "conversion_rate": round(self.conversion_rate, 4),
            "mean_value": round(self.mean_value, 4),
        }


@dataclass
class ExperimentConfig:
    """实验配置"""
    name: str                                     # 唯一名称
    description: str = ""
    experiment_type: ExperimentType = ExperimentType.AB_TEST
    variants: List[str] = field(default_factory=list)  # 变体名称列表
    metrics: List[str] = field(default_factory=list)    # 关注的指标
    traffic_fraction: float = 1.0                 # 流量比例 (0.0-1.0)
    bandit_algorithm: BanditAlgorithm = BanditAlgorithm.THOMPSON_SAMPLING
    epsilon: float = 0.1                          # epsilon-greedy 探索率
    min_sample_size: int = 100                    # 最小样本量
    significance_level: SignificanceLevel = SignificanceLevel.P95
    auto_stop: bool = False                       # 是否自动停止
    auto_stop_threshold: float = 0.95             # 自动停止置信度
    owner: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Experiment:
    """实验实例"""
    config: ExperimentConfig
    state: ExperimentState = ExperimentState.DRAFT
    variant_stats: Dict[str, VariantStats] = field(default_factory=dict)
    assignments: Dict[str, str] = field(default_factory=dict)  # user_id → variant
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    ended_at: float = 0.0
    winner: Optional[str] = None

    def __post_init__(self, **kw):
        if not self.variant_stats:
            for v in self.config.variants:
                self.variant_stats[v] = VariantStats(name=v)

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "name": self.config.name,
            "state": self.state.value,
            "type": self.config.experiment_type.value,
            "variants": {k: v.to_dict() for k, v in self.variant_stats.items()},
            "total_assignments": len(self.assignments),
            "winner": self.winner,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


# ═══════════════════════════════════════════════════════════
# 统计算法
# ═══════════════════════════════════════════════════════════

class Statistics:
    """统计检验工具"""

    @staticmethod
    def z_test_proportions(
        s1: int, n1: int, s2: int, n2: int,
    ) -> Tuple[float, float]:
        """双比例 Z 检验

        Returns:
            (z_score, p_value)
        """
        if n1 == 0 or n2 == 0:
            return 0.0, 1.0

        p1 = s1 / n1
        p2 = s2 / n2
        p_pool = (s1 + s2) / (n1 + n2)

        se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
        if se == 0:
            return 0.0, 1.0

        z = (p1 - p2) / se

        # 近似 p-value (双尾)
        p_value = 2 * (1 - Statistics._normal_cdf(abs(z)))
        return z, p_value

    @staticmethod
    def chi_squared(observed: List[List[float]], **kw) -> Tuple[float, float]:
        """卡方检验

        Args:
            observed: 2x2 列联表 [[a, b], [c, d]]

        Returns:
            (chi2, p_value)
        """
        if len(observed) < 2 or len(observed[0]) < 2:
            return 0.0, 1.0

        a, b = observed[0][0], observed[0][1]
        c, d = observed[1][0], observed[1][1]
        n = a + b + c + d
        if n == 0:
            return 0.0, 1.0

        # 期望值
        e_a = (a + b) * (a + c) / n
        e_b = (a + b) * (b + d) / n
        e_c = (c + d) * (a + c) / n
        e_d = (c + d) * (b + d) / n

        chi2 = 0.0
        for obs, exp in [(a, e_a), (b, e_b), (c, e_c), (d, e_d)]:
            if exp > 0:
                chi2 += (obs - exp) ** 2 / exp

        # 自由度 = 1, 近似 p-value
        p_value = 1 - Statistics._chi2_cdf(chi2, 1)
        return chi2, max(0.0, min(1.0, p_value))

    @staticmethod
    def is_significant(p_value: float, level: SignificanceLevel, **kw) -> bool:
        """判断是否显著"""
        alpha = float(level.value)
        return p_value < alpha

    @staticmethod
    def _normal_cdf(x: float, **kw) -> float:
        """标准正态分布 CDF (近似)"""
        # Abramowitz and Stegun 近似
        if x < 0:
            return 1 - Statistics._normal_cdf(-x)
        b0, b1, b2, b3, b4, b5 = 0.2316419, 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
        t = 1 / (1 + b0 * x)
        pdf = math.exp(-x * x / 2) / math.sqrt(2 * math.pi)
        return 1 - pdf * (b1 * t + b2 * t ** 2 + b3 * t ** 3 + b4 * t ** 4 + b5 * t ** 5)

    @staticmethod
    def _chi2_cdf(x: float, df: int, **kw) -> float:
        """卡方分布 CDF (近似, df=1)"""
        if x <= 0:
            return 0.0
        # Wilson-Hilferty 近似
        z = ((x / df) ** (1 / 3) - 1 + 2 / (9 * df)) / math.sqrt(2 / (9 * df))
        return Statistics._normal_cdf(z)

    @staticmethod
    def _gamma_inc(a: float, x: float, **kw) -> float:
        """不完全 gamma 函数 (简化)"""
        # 使用级数展开 (对于小 x)
        if x < a + 1:
            # 级数
            ap, sum_, delta = a, 1.0 / a, 1.0 / a
            for n in range(1, 100):
                ap += 1
                delta *= x / ap
                sum_ += delta
                if abs(delta) < abs(sum_) * 1e-10:
                    return sum_ * math.exp(-x + a * math.log(x) - math.lgamma(a + 1))
        # 连分数 (对于大 x)
        b = x + 1 - a
        c = 1.0 / 1e-30
        d = 1.0 / b
        h = d
        for n in range(1, 100):
            an = -n * (n - a)
            b += 2
            d = an * d + b
            if abs(d) < 1e-30:
                d = 1e-30
            c = b + an / c
            if abs(c) < 1e-30:
                c = 1e-30
            d = 1.0 / d
            delta = d * c
            h *= delta
            if abs(delta - 1) < 1e-10:
                return 1 - math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
        return 1.0


# ═══════════════════════════════════════════════════════════
# Bandit 算法
# ═══════════════════════════════════════════════════════════

class BanditSelector:
    """多臂老虎机选择器"""

    @staticmethod
    def thompson_sampling(
        variants: Dict[str, VariantStats],
    ) -> str:
        """汤普森采样

        从 Beta(successes + 1, failures + 1) 抽样,
        选择采样值最高的变体。
        """
        best_variant = None
        best_score = -1.0

        for name, stats in variants.items():
            alpha = stats.successes + 1
            beta = (stats.trials - stats.successes) + 1
            # Beta(α,β) 采样 = Gamma(α,1)/ (Gamma(α,1)+Gamma(β,1))
            sample = random.betavariate(max(1, alpha), max(1, beta))
            if sample > best_score:
                best_score = sample
                best_variant = name

        return best_variant or list(variants.keys())[0]

    @staticmethod
    def epsilon_greedy(
        variants: Dict[str, VariantStats], epsilon: float = 0.1,
    ) -> str:
        """Epsilon-Greedy

        以 ε 概率随机探索, 以 1-ε 概率选择当前最优。
        """
        if random.random() < epsilon:
            return random.choice(list(variants.keys()))

        best_variant = None
        best_rate = -1.0
        for name, stats in variants.items():
            rate = stats.conversion_rate if stats.trials > 0 else 0.5
            if rate > best_rate or (rate == best_rate and stats.trials == 0):
                best_rate = rate
                best_variant = name

        return best_variant or list(variants.keys())[0]

    @staticmethod
    def ucb(
        variants: Dict[str, VariantStats], total_trials: int,
    ) -> str:
        """上置信界 (UCB1)

        选择 mean + sqrt(2 * ln(N) / n_i) 最大的变体。
        """
        best_variant = None
        best_score = -float("inf")

        for name, stats in variants.items():
            if stats.trials == 0:
                return name  # 优先尝试未探索的变体
            mean = stats.conversion_rate
            exploration = math.sqrt(2 * math.log(max(1, total_trials)) / stats.trials)
            score = mean + exploration
            if score > best_score:
                best_score = score
                best_variant = name

        return best_variant or list(variants.keys())[0]


# ═══════════════════════════════════════════════════════════
# ExperimentEngine — 主类
# ═══════════════════════════════════════════════════════════

class ExperimentEngine:
    """实验引擎

    管理所有实验的生命周期、用户分配和结果统计。
    """

    def __init__(self, storage_path: str = "", **kw):
        self._experiments: Dict[str, Experiment] = {}
        self._lock = threading.RLock()
        self._storage_path = storage_path or os.path.join(
            os.path.expanduser("~"), ".meshctx", "experiments.json"
        )
        self._load_from_disk()

    # ── 实验管理 ────────────────────────────────────────────

    def create_experiment(
        self,
        name: str,
        variants: List[str],
        description: str = "",
        experiment_type: ExperimentType = ExperimentType.AB_TEST,
        traffic_fraction: float = 1.0,
        metrics: List[str] = None,
        **kwargs,
    ) -> Experiment:
        """创建新实验

        Args:
            name: 实验名称 (唯一)
            variants: 变体名称列表, e.g. ["control", "treatment"]
            description: 描述
            experiment_type: 实验类型
            traffic_fraction: 流量比例
            metrics: 关注指标
        """
        with self._lock:
            if name in self._experiments:
                raise ValueError(f"Experiment '{name}' already exists")

            if len(variants) < 2:
                raise ValueError("At least 2 variants required")

            config = ExperimentConfig(
                name=name,
                description=description,
                experiment_type=experiment_type,
                variants=variants,
                metrics=metrics or [],
                traffic_fraction=traffic_fraction,
                **kwargs,
            )
            exp = Experiment(config=config)
            self._experiments[name] = exp
            logger.info(f"Created experiment: {name} with variants={variants}")
        self._save_to_disk()
        return exp

    def start_experiment(self, name: str, **kw) -> bool:
        """启动实验"""
        with self._lock:
            exp = self._experiments.get(name)
            if not exp or exp.state != ExperimentState.DRAFT:
                return False
            exp.state = ExperimentState.RUNNING
            exp.started_at = time.time()
            logger.info(f"Started experiment: {name}")
        self._save_to_disk()
        return True

    def pause_experiment(self, name: str, **kw) -> bool:
        """暂停实验"""
        with self._lock:
            exp = self._experiments.get(name)
            if not exp or exp.state != ExperimentState.RUNNING:
                return False
            exp.state = ExperimentState.PAUSED
            logger.info(f"Paused experiment: {name}")
        return True

    def resume_experiment(self, name: str, **kw) -> bool:
        """恢复实验"""
        with self._lock:
            exp = self._experiments.get(name)
            if not exp or exp.state != ExperimentState.PAUSED:
                return False
            exp.state = ExperimentState.RUNNING
            logger.info(f"Resumed experiment: {name}")
        return True

    def complete_experiment(self, name: str, **kw) -> Optional[Dict[str, Any]]:
        """完成实验并返回结果分析"""
        with self._lock:
            exp = self._experiments.get(name)
            if not exp:
                return None
            exp.state = ExperimentState.COMPLETED
            exp.ended_at = time.time()

            # 自动选择优胜者
            winner = self._select_winner(exp)
            exp.winner = winner
            logger.info(f"Completed experiment: {name}, winner={winner}")

        results = self.get_results(name)
        self._save_to_disk()
        return results

    def archive_experiment(self, name: str, **kw) -> bool:
        """归档实验"""
        with self._lock:
            exp = self._experiments.get(name)
            if not exp:
                return False
            exp.state = ExperimentState.ARCHIVED
        self._save_to_disk()
        return True

    # ── 用户分配 ────────────────────────────────────────────

    def assign(self, experiment_name: str, user_id: str, **kw) -> Optional[str]:
        """将用户分配到实验变体

        使用一致性哈希保证同一用户总是分配到相同变体。
        """
        with self._lock:
            exp = self._experiments.get(experiment_name)
            if not exp or exp.state not in (ExperimentState.RUNNING, ExperimentState.PAUSED):
                return None

            # 检查流量比例
            bucket = self._get_user_bucket(user_id, experiment_name)
            if bucket > exp.config.traffic_fraction * 100:
                return None

            # 检查是否已分配
            if user_id in exp.assignments:
                return exp.assignments[user_id]

            # 按实验类型分配变体
            variants = exp.variant_stats

            if exp.config.experiment_type == ExperimentType.MULTI_ARM_BANDIT:
                total_trials = sum(s.trials for s in variants.values())

                if exp.config.bandit_algorithm == BanditAlgorithm.THOMPSON_SAMPLING:
                    variant = BanditSelector.thompson_sampling(variants)
                elif exp.config.bandit_algorithm == BanditAlgorithm.UCB:
                    variant = BanditSelector.ucb(variants, total_trials)
                else:
                    variant = BanditSelector.epsilon_greedy(
                        variants, exp.config.epsilon,
                    )
            else:
                # 固定比例: 按哈希均匀分配
                variant_names = sorted(variants.keys())
                slice_size = 100.0 / len(variant_names)
                idx = int(bucket / slice_size)
                idx = min(idx, len(variant_names) - 1)
                variant = variant_names[idx]

            exp.assignments[user_id] = variant
            exp.variant_stats[variant].impressions += 1
            logger.debug(f"Assigned {user_id} → {variant} (exp={experiment_name})")

        self._save_to_disk()
        return variant

    # ── 结果记录 ────────────────────────────────────────────

    def record_result(
        self,
        experiment_name: str,
        user_id: str,
        metric: str,
        value: float,
    ) -> bool:
        """记录实验结果

        Args:
            experiment_name: 实验名
            user_id: 用户 ID
            metric: 指标名
            value: 指标值 (二元指标用 0/1 表示成功/失败)
        """
        with self._lock:
            exp = self._experiments.get(experiment_name)
            if not exp:
                return False

            variant = exp.assignments.get(user_id)
            if not variant:
                return False

            stats = exp.variant_stats[variant]
            stats.trials += 1
            stats.total_value += value
            if value >= 0.5:  # 阈值判定为成功 (适用于二元指标)
                stats.successes += 1

            # 保留最近 1000 个值用于详细分析
            stats.values.append(value)
            if len(stats.values) > 1000:
                stats.values = stats.values[-1000:]

            logger.debug(
                f"Recorded: {user_id}@{variant} metric={metric} value={value}"
            )

        # 自动停止检查
        if exp.config.auto_stop:
            self._check_auto_stop(experiment_name)

        self._save_to_disk()
        return True

    # ── 分析 ────────────────────────────────────────────────

    def get_results(self, experiment_name: str, **kw) -> Optional[Dict[str, Any]]:
        """获取实验结果分析"""
        with self._lock:
            exp = self._experiments.get(experiment_name)
            if not exp:
                return None

            variants = exp.variant_stats
            baseline_name = exp.config.variants[0] if exp.config.variants else None
            baseline = variants.get(baseline_name) if baseline_name else None

            comparisons = []
            if baseline:
                for vname, vstats in variants.items():
                    if vname == baseline_name:
                        continue
                    z, p = Statistics.z_test_proportions(
                        vstats.successes, vstats.trials,
                        baseline.successes, baseline.trials,
                    )
                    comparisons.append({
                        "variant": vname,
                        "vs_baseline": baseline_name,
                        "z_score": round(z, 4),
                        "p_value": round(p, 4),
                        "significant": Statistics.is_significant(
                            p, exp.config.significance_level,
                        ),
                    })

            return {
                "experiment": experiment_name,
                "state": exp.state.value,
                "variants": {k: v.to_dict() for k, v in variants.items()},
                "comparisons": comparisons,
                "winner": exp.winner,
                "duration_days": (
                    ((exp.ended_at or time.time()) - exp.started_at) / 86400
                    if exp.started_at > 0 else 0
                ),
            }

    def _select_winner(self, exp: Experiment, **kw) -> Optional[str]:
        """自动选择优胜者"""
        best_variant = None
        best_rate = -1.0
        for name, stats in exp.variant_stats.items():
            if stats.trials >= exp.config.min_sample_size:
                if stats.conversion_rate > best_rate:
                    best_rate = stats.conversion_rate
                    best_variant = name
        return best_variant

    def _check_auto_stop(self, experiment_name: str, **kw) -> None:
        """检查是否应该自动停止实验"""
        exp = self._experiments.get(experiment_name)
        if not exp or exp.state != ExperimentState.RUNNING:
            return

        # 检查最小样本量
        for stats in exp.variant_stats.values():
            if stats.trials < exp.config.min_sample_size:
                return

        # 检查显著性
        results = self.get_results(experiment_name)
        if results:
            for comp in results.get("comparisons", []):
                if comp.get("significant"):
                    conf = 1 - float(comp.get("p_value", 1))
                    if conf >= exp.config.auto_stop_threshold:
                        logger.info(f"Auto-stopping {experiment_name}: significant result found")
                        self.complete_experiment(experiment_name)
                        return

    def get_experiment(self, name: str, **kw) -> Optional[Experiment]:
        """获取实验"""
        with self._lock:
            return self._experiments.get(name)

    def list_experiments(
        self, state: ExperimentState = None,
    ) -> List[Experiment]:
        """列出实验"""
        with self._lock:
            exps = list(self._experiments.values())
            if state:
                exps = [e for e in exps if e.state == state]
            return sorted(exps, key=lambda e: e.created_at, reverse=True)

    def _get_user_bucket(self, user_id: str, salt: str, **kw) -> float:
        """计算用户哈希桶 (0-100)"""
        key = f"{salt}:{user_id}".encode("utf-8")
        hash_hex = hashlib.md5(key).hexdigest()
        hash_int = int(hash_hex[:8], 16)
        return (hash_int / 0xFFFFFFFF) * 100.0

    def _save_to_disk(self, **kw) -> None:
        try:
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
            with self._lock:
                data = {
                    "experiments": {
                        k: {
                            "config": {
                                "name": v.config.name,
                                "description": v.config.description,
                                "experiment_type": v.config.experiment_type.value,
                                "variants": v.config.variants,
                                "metrics": v.config.metrics,
                                "traffic_fraction": v.config.traffic_fraction,
                            },
                            "state": v.state.value,
                            "variant_stats": {
                                vn: vs.to_dict() for vn, vs in v.variant_stats.items()
                            },
                            "created_at": v.created_at,
                            "started_at": v.started_at,
                            "ended_at": v.ended_at,
                            "winner": v.winner,
                        }
                        for k, v in self._experiments.items()
                    },
                    "saved_at": time.time(),
                }
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save experiments: {e}")

    def _load_from_disk(self, **kw) -> None:
        if not os.path.exists(self._storage_path):
            return
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
            for key, ed in data.get("experiments", {}).items():
                cfg = ed.get("config", {})
                config = ExperimentConfig(
                    name=cfg.get("name", key),
                    description=cfg.get("description", ""),
                    experiment_type=ExperimentType(cfg.get("experiment_type", "ab_test")),
                    variants=cfg.get("variants", []),
                    metrics=cfg.get("metrics", []),
                    traffic_fraction=cfg.get("traffic_fraction", 1.0),
                )
                exp = Experiment(config=config)
                exp.state = ExperimentState(ed.get("state", "draft"))
                exp.created_at = ed.get("created_at", time.time())
                exp.started_at = ed.get("started_at", 0.0)
                exp.ended_at = ed.get("ended_at", 0.0)
                exp.winner = ed.get("winner")

                for vname, vs in ed.get("variant_stats", {}).items():
                    if vname in exp.variant_stats:
                        exp.variant_stats[vname].impressions = vs.get("impressions", 0)
                        exp.variant_stats[vname].successes = vs.get("successes", 0)
                        exp.variant_stats[vname].trials = vs.get("trials", 0)
                        exp.variant_stats[vname].total_value = vs.get("mean_value", 0) * vs.get("trials", 0)

                self._experiments[key] = exp
            logger.info(f"Loaded {len(self._experiments)} experiments from disk")
        except Exception as e:
            logger.error(f"Failed to load experiments: {e}")


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_global_experiment_engine: Optional[ExperimentEngine] = None
_global_ee_lock = threading.Lock()


def get_experiment_engine(storage_path: str = "") -> ExperimentEngine:
    """获取全局 ExperimentEngine 单例"""
    global _global_experiment_engine
    if _global_experiment_engine is None:
        with _global_ee_lock:
            if _global_experiment_engine is None:
                _global_experiment_engine = ExperimentEngine(storage_path=storage_path)
                logger.info("Created global ExperimentEngine instance")
    return _global_experiment_engine


# ═══════════════════════════════════════════════════════════
# CLI 诊断
# ═══════════════════════════════════════════════════════════

def _cli_main():
    """CLI 诊断"""
    print("=" * 60)
    print("  meshctx Experiment Engine — 诊断工具")
    print("=" * 60)

    # 使用临时存储路径, 避免持久化残留干扰
    import tempfile
    tmp_storage = os.path.join(tempfile.gettempdir(), "meshctx_test_experiments.json")
    if os.path.exists(tmp_storage):
        os.remove(tmp_storage)
    engine = ExperimentEngine(storage_path=tmp_storage)

    # 创建 A/B 测试
    exp = engine.create_experiment(
        "cta_button_color",
        variants=["green", "blue", "red"],
        description="CTA 按钮颜色 A/B 测试",
    )
    engine.start_experiment("cta_button_color")

    # 模拟用户分配
    users = [f"user_{i}" for i in range(1000)]
    for uid in users:
        variant = engine.assign("cta_button_color", uid)
        # 模拟转化: 绿色 10%, 蓝色 12%, 红色 8%
        if variant == "green":
            converted = random.random() < 0.10
        elif variant == "blue":
            converted = random.random() < 0.12
        else:
            converted = random.random() < 0.08
        engine.record_result("cta_button_color", uid, "click", 1.0 if converted else 0.0)

    # 分析结果
    results = engine.get_results("cta_button_color")
    print(f"\n实验: {results['experiment']}")
    print(f"状态: {results['state']}")
    print("\n变体统计:")
    for vname, vstats in results["variants"].items():
        print(f"  {vname}: {vstats['trials']} trials, "
              f"CR={vstats['conversion_rate']:.3f}")

    print("\n显著性检验:")
    for comp in results.get("comparisons", []):
        sig = "✅ SIGNIFICANT" if comp["significant"] else "❌ not significant"
        print(f"  {comp['variant']} vs {comp['vs_baseline']}: "
              f"z={comp['z_score']:.2f}, p={comp['p_value']:.4f} → {sig}")

    print("\n✅ Experiment Engine 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    _cli_main()
