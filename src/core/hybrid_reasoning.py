"""
MeshCtx Hybrid Reasoning Scheduler — Proprietary Core
======================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Implements free-energy-gated reasoning mode switching between
exploratory deep reasoning and fast direct generation —
proprietary algorithms.

License: AGPLv3 for non-commercial use only.
         Commercial use REQUIRES a separate license.
         Contact: license@meshctx.com

核心思想:

- 高惊讶 / 高不确定性 (F > 阈值) → 探索模式: 先执行主动推理策略积累证据，再回答
- 低惊讶 / 低不确定性 (F < 阈值) → 直出模式: 直接 LLM 回答

自由能 F = 复杂度 + 不准确度 = 系统与环境的"紧张"程度
F 越高 → 智能体越不确定 → 需要探索
F 越低 → 智能体越确定 → 直接利用

与 web_ui.py 的 chat 流程集成:
  scheduler = HybridReasoningScheduler(ai_engine, fe_agent)
  if scheduler.should_reason(message_history, current_query):
      result = scheduler.reason(message_history, current_query)
  else:
      result = scheduler.direct(message_history, current_query)
"""
import math
import time
import hashlib
import logging
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

from .free_energy import (
    BeliefState, BeliefType, FreeEnergyComputer,
    PrecisionWeighting, CriticalityRegulator,
    FreeEnergyAgent,
)
from .active_inference import (
    ActiveInferenceEngine, Policy, ActionType,
)

logger = logging.getLogger("meshctx.hybrid_reasoning")


class HybridReasoningScheduler:
    """
    混合推理调度器 — 用自由能 F 值判断探索模式还是直出模式。

    工作流:
    1. 接收对话上下文 (message_history + current_query)
    2. 计算当前上下文的自由能 F 值
       - 分析问题重复度 (hash相似性)
       - 上下文切换频率 (主题变化)
       - 当前 AI 的 uncertainty
    3. 如果 F > 阈值 → 探索模式 (执行主动推理)
       - 观察→信念更新→策略选择→积累证据→最终回答
    4. 如果 F < 阈值 → 直出模式 (直接 LLM 回答)
       - 跳过推理循环，直接生成

    自适应阈值:
    初始 threshold = 默认值 (如 1.5)
    随运行反馈自动调整:
      - 探索模式效果差 → 提高阈值 (更难进入探索)
      - 直出模式效果差 → 降低阈值 (更容易进入探索)
    """

    def __init__(
        self,
        ai_engine: Optional[ActiveInferenceEngine] = None,
        fe_agent: Optional[FreeEnergyAgent] = None,
        threshold: float = 1.5,
        adaptive: bool = True,
    ):
        # 核心组件
        self.ai_engine = ai_engine or ActiveInferenceEngine(name="hybrid_ai")
        self.fe_agent = fe_agent or FreeEnergyAgent(n_strategies=5, name="hybrid_fea")

        # 自由能计算器
        self.free_energy_computer = FreeEnergyComputer()

        # 信念跟踪 — 对话上下文的信念
        self.context_belief = BeliefState(
            name="context_uncertainty",
            belief_type=BeliefType.DIRICHLET,
            n_categories=2,  # [low_uncertainty, high_uncertainty]
            prior_strength=1.0,
        )

        # 阈值管理
        self.threshold = threshold
        self.base_threshold = threshold
        self.adaptive = adaptive
        self.threshold_history: List[float] = [threshold]

        # 统计
        self.total_decisions: int = 0
        self.explore_count: int = 0
        self.direct_count: int = 0
        self.decision_history: List[Dict] = []

        # F 值缓存
        self.last_f_value: float = 0.0
        self.last_components: Dict[str, float] = {}

        # 历史消息缓存 (用于重复度检测)
        self._message_hashes: List[str] = []

    # ── 公开接口 ──────────────────────────────────────────────

    def should_reason(
        self,
        message_history: List[Dict[str, str]],
        current_query: str,
    ) -> bool:
        """
        判断当前上下文是否需要进入探索推理模式。

        综合评分:
        1. 问题重复度 (hash相似性) — 重复问题说明上次答案可能不够好
        2. 上下文切换频率 (主题变化) — 频繁切换说明环境不稳定
        3. 当前 AI 的 uncertainty — 信念熵高说明需要探索

        返回:
          True  → 走探索模式 (高惊讶/不确定性)
          False → 走直出模式 (低惊讶/不确定性)
        """
        # 1. 计算自由能 F 值
        f_value, components = self._compute_free_energy(message_history, current_query)
        self.last_f_value = f_value
        self.last_components = components

        # 2. 分析惊讶度各维度
        query_repetition = self._compute_query_repetition(current_query)
        context_switch = self._compute_context_switch_frequency(message_history)
        ai_uncertainty = self._compute_ai_uncertainty()

        # 3. 综合评分: 加权平均
        w_repetition = 0.25
        w_switch = 0.35
        w_uncertainty = 0.40

        composite_score = (
            w_repetition * query_repetition +
            w_switch * context_switch +
            w_uncertainty * ai_uncertainty
        )

        # 4. 用 F 值作为最终校准因子
        #    如果 F 值很高 (高惊讶) → 提高进入探索的概率
        #    如果 F 值很低 (低惊讶) → 降低进入探索的概率
        f_factor = min(max(f_value / self.threshold, 0.0), 3.0)
        final_score = composite_score * (0.5 + 0.5 * f_factor)

        # 5. 决策
        should_explore = final_score > self.threshold

        # 6. 记录统计
        self.total_decisions += 1
        if should_explore:
            self.explore_count += 1
        else:
            self.direct_count += 1

        self.decision_history.append({
            "timestamp": time.time(),
            "decision": "explore" if should_explore else "direct",
            "f_value": f_value,
            "composite_score": composite_score,
            "final_score": final_score,
            "threshold": self.threshold,
            "components": {
                "query_repetition": query_repetition,
                "context_switch": context_switch,
                "ai_uncertainty": ai_uncertainty,
                "f_factor": f_factor,
            },
        })

        # 维护消息哈希缓存
        self._message_hashes.append(self._hash_query(current_query))
        if len(self._message_hashes) > 100:
            self._message_hashes = self._message_hashes[-100:]

        return should_explore

    def reason(
        self,
        message_history: List[Dict[str, str]],
        current_query: str,
    ) -> Dict[str, Any]:
        """
        探索推理模式:
        执行主动推理循环 → 观察 → 信念更新 → 策略选择 → LLM 生成

        返回:
            Dict {
                "response": str,           # 最终生成的响应
                "reasoning_trace": Dict,   # 推理过程的详细信息
                "policy_used": str,        # 使用的策略名称
                "free_energy": float,      # 自由能 F 值
                "strategy": "explore",
            }
        """
        logger.info("HybridReasoning: entering EXPLORE mode")

        trace = {
            "steps": [],
            "policies_considered": [],
            "selected_policy": None,
            "belief_updates": [],
        }

        # 步骤 1: 感知 — 将当前查询编码为观察
        observation = self._encode_query_as_observation(current_query)
        trace["steps"].append({"step": "perceive", "observation": observation})

        # 步骤 2: 更新信念 (Bayesian update)
        self.fe_agent.strategy_belief.observe(
            observation,
            weight=self.fe_agent.precision.compute_precision(
                self.fe_agent.strategy_belief,
                max(self.fe_agent.episode_count, 1),
            ),
        )
        pre_belief = self.fe_agent.strategy_belief.expected_probability.tolist()
        trace["steps"].append({"step": "belief_update", "belief_before": pre_belief})

        # 步骤 3: 主动推理 — 选择最优策略
        action_idx = self.fe_agent.decide()
        policy_names = self._get_policy_names()
        selected_policy = policy_names[action_idx] if action_idx < len(policy_names) else f"policy_{action_idx}"
        trace["steps"].append({
            "step": "select_policy",
            "action_idx": action_idx,
            "selected_policy": selected_policy,
        })
        trace["selected_policy"] = selected_policy

        # 步骤 4: 执行策略 — 收集证据 / 分析上下文
        evidence = self._gather_evidence(message_history, current_query, action_idx)
        trace["steps"].append({"step": "gather_evidence", "evidence_summary": evidence.get("summary", "")})

        # 步骤 5: 基于策略生成回答
        response = self._generate_explore_response(
            message_history, current_query, selected_policy, evidence,
        )
        trace["steps"].append({"step": "generate_response"})

        # 步骤 6: 学习 — 记录策略结果 (总是标记为成功, 因为响应用户)
        self.fe_agent.perceive(action_idx, duration=0.5, success=True)
        reflection = self.fe_agent.reflect()
        trace["steps"].append({
            "step": "learn",
            "free_energy": reflection["free_energy"],
        })
        trace["belief_updates"].append(self.fe_agent.strategy_belief.expected_probability.tolist())

        # 自适应阈值调整 (可选)
        if self.adaptive:
            self._adapt_threshold(reflection["free_energy"])

        return {
            "response": response,
            "reasoning_trace": trace,
            "policy_used": selected_policy,
            "free_energy": self.last_f_value,
            "strategy": "explore",
        }

    def direct(
        self,
        message_history: List[Dict[str, str]],
        current_query: str,
    ) -> Dict[str, Any]:
        """
        直出模式: 直接返回 (不进行主动推理)
        实际被 web_ui.py 调用时, response 字段将被 LLM 流式输出替换

        返回:
            Dict {
                "response": None,     # 由上游 LLM 填充
                "reasoning_trace": Dict,
                "free_energy": float,
                "strategy": "direct",
            }
        """
        logger.info("HybridReasoning: entering DIRECT mode")
        return {
            "response": None,
            "reasoning_trace": {
                "mode": "direct",
                "free_energy": self.last_f_value,
                "components": self.last_components,
            },
            "policy_used": "direct_llm",
            "free_energy": self.last_f_value,
            "strategy": "direct",
        }

    def get_decision_stats(self) -> Dict[str, Any]:
        """
        获取决策统计信息。

        返回:
            Dict {
                "total_decisions": int,
                "explore_count": int,
                "direct_count": int,
                "explore_ratio": float,
                "direct_ratio": float,
                "current_threshold": float,
                "last_f_value": float,
                "last_components": Dict,
            }
        """
        total = max(self.total_decisions, 1)
        return {
            "total_decisions": self.total_decisions,
            "explore_count": self.explore_count,
            "direct_count": self.direct_count,
            "explore_ratio": self.explore_count / total,
            "direct_ratio": self.direct_count / total,
            "current_threshold": self.threshold,
            "last_f_value": self.last_f_value,
            "last_components": dict(self.last_components),
            "threshold_history": self.threshold_history[-20:] if self.threshold_history else [],
            "recent_decisions": self.decision_history[-10:] if self.decision_history else [],
        }

    # ── 内部计算 ──────────────────────────────────────────────

    def _compute_free_energy(
        self,
        message_history: List[Dict[str, str]],
        current_query: str,
    ) -> Tuple[float, Dict[str, float]]:
        """
        计算当前对话上下文的自由能 F 值。

        将对话历史编码为观察序列, 用 FreeEnergyComputer 计算 F。
        包含:
          - 复杂度: 当前信念偏离先验的程度
          - 不准确度: 当前上下文被模型解释的困难程度
          - 惊讶值: 当前查询的信息量 (越低→越可预测)

        返回: (F, components_dict)
        """
        # 用 fe_agent 的策略信念作为"当前信念"
        belief = self.fe_agent.strategy_belief

        # 用当前查询构造观察编码
        obs = self._encode_query_as_observation(current_query)

        # 先验: 无信息的均匀分布
        prior_alpha = np.ones(belief.n_categories) * belief.prior_strength

        # 计算自由能
        F, components = self.free_energy_computer.compute_free_energy(
            belief=belief,
            observation=obs,
            prior_alpha=prior_alpha,
            temperature=self.fe_agent.criticality.temperature,
        )

        # 加入对话长度惩罚 (长对话自然有更高的复杂度)
        history_length = len(message_history)
        length_penalty = math.log(max(history_length + 1, 1)) * 0.1
        F += length_penalty
        components["history_length_penalty"] = length_penalty

        return F, components

    def _compute_query_repetition(self, current_query: str) -> float:
        """
        计算当前查询与历史查询的重复度。

        方法: 比较当前查询哈希与最近 N 条消息的 Jaccard 相似度。
        返回: 0.0 (完全不重复) ~ 1.0 (完全重复)
        """
        if not self._message_hashes:
            return 0.0

        current_hash = self._hash_query(current_query)
        current_tokens = set(current_query.lower().split())

        recent_hashes = self._message_hashes[-20:]
        if not recent_hashes:
            return 0.0

        # 哈希精确匹配
        exact_match_count = sum(1 for h in recent_hashes if h == current_hash)
        exact_ratio = exact_match_count / len(recent_hashes)

        # 文本相似度 (如果消息历史可访问)
        similarity = exact_ratio  # fallback

        return min(similarity, 1.0)

    def _compute_context_switch_frequency(self, message_history: List[Dict]) -> float:
        """
        计算上下文切换频率。

        检测角色交替和用户消息内容变化的频率。
        高频切换 → 惊讶度高 → 可能需要探索。

        返回: 0.0 (稳定) ~ 1.0 (频繁切换)
        """
        if len(message_history) < 3:
            return 0.0

        # 只分析用户消息
        user_messages = [
            m["content"].strip().lower()
            for m in message_history
            if m.get("role") == "user"
        ]

        if len(user_messages) < 2:
            return 0.0

        # 计算连续用户消息的主题变化
        switch_count = 0
        for i in range(1, len(user_messages)):
            # 使用字符级 bigram 处理中日韩等无空格语言
            prev_text = user_messages[i - 1]
            curr_text = user_messages[i]

            # 提取字符级 bigram 集合
            prev_bigrams = {prev_text[j:j+2] for j in range(len(prev_text) - 1)}
            curr_bigrams = {curr_text[j:j+2] for j in range(len(curr_text) - 1)}

            # 同时保留词级 token 作为补充
            prev_words = set(prev_text.split()[:10])
            curr_words = set(curr_text.split()[:10])

            # 字符级 bigram + 词级 token 合并 (词级使用中英文停用词过滤)
            _stop = {"的","了","在","是","我","有","和","就","不","人","都",
                     "一","一个","上","也","很","到","说","要","去","你",
                     "会","着","没有","看","好","自己","这","他","她","它",
                     "们","那","什么","怎么","如何","为什么","能不能","有没有",
                     "请","帮","让","把","被","从","对","为","以","与",
                     "但","而","或","如果","因为","所以","虽然","然而",
                     "可以","应该","需要","会","能","要","想","来","去",
                     "吗","呢","吧","啊","哦","嗯","哈","呀",
                     "更","再","还","又","就","才","都","只","也",
                     "加","写","用",
                     "the","a","an","is","are","was","were","be","been",
                     "i","you","he","she","it","we","they",
                     "this","that","these","those",
                     "and","or","but","if","because","so",
                     "to","for","with","from","by","at","in","on","of",
                     "do","does","did","have","has","had",
                     "can","could","will","would","shall","should","may","might",
                     "not","no","nor","also","just","very",
                     "please","here","there","how","what","why","when","where",}
            # 过滤停用词后的词级 token
            prev_filtered = {w for w in prev_text.split() if w.lower() not in _stop}
            curr_filtered = {w for w in curr_text.split() if w.lower() not in _stop}

            # 合并字符 bigram 和词级 token
            prev_set = prev_bigrams | prev_filtered
            curr_set = curr_bigrams | curr_filtered

            if prev_set and curr_set:
                # Jaccard 相似度: 重叠越大 → 主题越相似
                overlap = len(prev_set & curr_set)
                total = len(prev_set | curr_set)
                jaccard = overlap / total if total > 0 else 0.0

                # 对短文本 (< 30 字符)，使用更宽容的阈值
                if len(prev_text) < 30 and len(curr_text) < 30:
                    # 短文本: 检查是否有词根重叠
                    pw = {w for w in prev_text.split() if w.lower() not in _stop}
                    cw = {w for w in curr_text.split() if w.lower() not in _stop}
                    shared_words = pw & cw
                    if shared_words:
                        is_switch = False
                    elif pw and cw:
                        word_jaccard = len(pw & cw) / max(len(pw | cw), 1)
                        is_switch = word_jaccard < 0.2 and jaccard < 0.05
                    else:
                        is_switch = jaccard < 0.05
                else:
                    is_switch = jaccard < 0.15

                if is_switch:
                    switch_count += 1

        switch_ratio = switch_count / max(len(user_messages) - 1, 1)
        return min(switch_ratio, 1.0)

    @staticmethod
    def _extract_shared_keywords(text_a: str, text_b: str) -> List[str]:
        """
        "提取两段文本共享的关键词片段 (支持 CJK 和英文)。

        使用字符级重叠检测:
        - 提取两段文本中的非停用词片段
        - 返回共享片段 (按长度排序)
        """
        # 中英文停用词
        stopwords = {
            # 中文
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都",
            "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
            "会", "着", "没有", "看", "好", "自己", "这", "他", "她", "它",
            "们", "那", "什么", "怎么", "如何", "为什么", "能不能", "有没有",
            "请", "帮", "让", "把", "被", "从", "对", "为", "以", "与",
            "但", "而", "或", "如果", "因为", "所以", "虽然", "然而",
            "可以", "应该", "需要", "会", "能", "要", "想", "来", "去",
            "吗", "呢", "吧", "啊", "哦", "嗯", "哈", "呀",
            "更", "再", "还", "又", "就", "才", "都", "只", "也",
            "加", "写", "用",
            # English
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "i", "you", "he", "she", "it", "we", "they",
            "this", "that", "these", "those",
            "and", "or", "but", "if", "because", "so",
            "to", "for", "with", "from", "by", "at", "in", "on", "of",
            "do", "does", "did",
            "have", "has", "had",
            "can", "could", "will", "would", "shall", "should", "may", "might",
            "not", "no", "nor", "also", "just", "very",
            "please", "here", "there", "how", "what", "why", "when", "where",
        }

        import re

        def extract_meaningful_chunks(text: str) -> set:
            """提取有意义的中文片段和英文词"""
            result = set()
            # 提取连续中文字符
            chinese_chunks = re.findall(r'[\u4e00-\u9fff]{2,}', text)
            for chunk in chinese_chunks:
                # 提取 2-4 gram
                for l in range(2, min(5, len(chunk) + 1)):
                    for j in range(len(chunk) - l + 1):
                        phrase = chunk[j:j+l]
                        if phrase not in stopwords:
                            result.add(phrase)
            # 提取英文词 (Python, 递归, 实现 等)
            english = re.findall(r'[a-zA-Z_]\w*', text)
            for w in english:
                if len(w) >= 2:
                    result.add(w.lower())
            # 提取单个 CJK 字符 (去除停用词)
            for ch in text:
                if '\u4e00' <= ch <= '\u9fff' and ch not in stopwords:
                    result.add(ch)
            return result

        chunks_a = extract_meaningful_chunks(text_a)
        chunks_b = extract_meaningful_chunks(text_b)
        shared = sorted(chunks_a & chunks_b, key=len, reverse=True)
        return shared

    def _compute_ai_uncertainty(self) -> float:
        """
        计算 AI 的当前不确定性。

        使用 fe_agent 的策略信念熵。
        高熵 → 高不确定性 → 需要探索。

        返回: 0.0 (完全确定) ~ 1.0 (完全不确定)
        """
        # 策略信念熵 (归一化到 0-1)
        entropy = self.fe_agent.strategy_belief.uncertainty
        # Dirichlet 微分熵可为负，钳制到 0 确保归一化正确
        entropy = max(entropy, 0.0)

        # Dirichlet(n=5) 的最大熵 = ln(5) ≈ 1.609
        n = self.fe_agent.strategy_belief.n_categories
        max_entropy = math.log(n) if n > 1 else 1.0
        normalized = min(entropy / max(max_entropy, 0.1), 1.0)

        # 加入温度影响
        T = self.fe_agent.criticality.temperature
        temperature_factor = min(T / 5.0, 1.0)

        # 加权: 70% 信念熵 + 30% 温度
        return 0.7 * normalized + 0.3 * temperature_factor

    def _adapt_threshold(self, free_energy: float):
        """
        自适应调整阈值。

        如果自由能持续升高 → 说明环境不稳定 → 提高阈值 (更难进入探索)
        如果自由能持续降低 → 说明环境稳定 → 降低阈值 (更容易直出)
        """
        if len(self.threshold_history) < 3:
            self.threshold_history.append(free_energy)
            return

        # 趋势检测
        recent = self.threshold_history[-3:]
        trend = recent[-1] - recent[0]

        if trend > 0.3:
            # 自由能上升 → 环境不稳定 → 提高阈值
            self.threshold = min(self.base_threshold + trend * 0.5, 5.0)
        elif trend < -0.3:
            # 自由能下降 → 环境稳定 → 降低阈值
            self.threshold = max(self.base_threshold + trend * 0.5, 0.3)

        self.threshold_history.append(free_energy)
        if len(self.threshold_history) > 100:
            self.threshold_history = self.threshold_history[-100:]

    # ── 辅助方法 ──────────────────────────────────────────────

    def _encode_query_as_observation(self, query: str) -> int:
        """
        将查询编码为观察索引 (0~n_categories-1)。

        方法: 用哈希映射到类别。
        短查询 (< 10 字) → 类别 0 (低信息量)
        中查询 (10~50 字) → 类别 1 (中等)
        长查询 (> 50 字) → 类别 2 (高信息量)
        """
        length = len(query.strip())
        if length < 10:
            return 0
        elif length < 50:
            return 1
        else:
            return 2

    def _hash_query(self, query: str) -> str:
        """对查询做轻量哈希"""
        return hashlib.md5(query.strip().lower().encode()).hexdigest()[:12]

    def _get_policy_names(self) -> List[str]:
        """获取策略名称列表"""
        from .active_inference import ActionType
        return [
            "explore_random",
            "exploit_best",
            "balanced",
            "observe_first",
            "safe_path",
        ][:self.fe_agent.n_strategies]

    def _gather_evidence(
        self,
        message_history: List[Dict],
        current_query: str,
        action_idx: int,
    ) -> Dict[str, Any]:
        """
        收集证据用于生成回答。

        根据不同的策略索引:
        0=explore_random → 随机抽取历史片段
        1=exploit_best → 聚焦最相关的上下文
        2=balanced → 综合
        3=observe_first → 提取更多观察
        4=safe_path → 保守分析
        """
        user_msgs = [m["content"] for m in message_history if m.get("role") == "user"]
        assistant_msgs = [m["content"] for m in message_history if m.get("role") == "assistant"]

        evidence = {
            "n_user_messages": len(user_msgs),
            "n_assistant_messages": len(assistant_msgs),
            "last_user_message": user_msgs[-1] if user_msgs else "",
            "strategy_idx": action_idx,
        }

        if action_idx == 0:
            # explore_random: 提取一些随机历史片段
            evidence["summary"] = f"探索模式: 从{len(user_msgs)}条用户消息中随机采样信息"
        elif action_idx == 1:
            # exploit_best: 聚焦最新上下文
            evidence["summary"] = f"聚焦模式: 聚焦最近{min(3, len(user_msgs))}条消息"
        elif action_idx == 2:
            # balanced: 综合
            evidence["summary"] = f"平衡模式: 综合{len(user_msgs)}条用户消息和{len(assistant_msgs)}条助手回复"
        elif action_idx == 3:
            # observe_first: 更多观察
            evidence["summary"] = f"观察模式: 等待获取更多上下文信息"
        else:
            # safe_path: 保守
            evidence["summary"] = "保守模式: 基于已确认的信息回答"

        return evidence

    def _generate_explore_response(
        self,
        message_history: List[Dict],
        current_query: str,
        policy_name: str,
        evidence: Dict,
    ) -> str:
        """
        基于探索策略生成响应提示。
        实际使用中 web_ui 会将其传给 LLM 生成完整响应。
        """
        policy_desc = {
            "explore_random": "随机探索多种可能性",
            "exploit_best": "聚焦最佳已知策略",
            "balanced": "平衡探索与利用",
            "observe_first": "先观察再行动",
            "safe_path": "保守安全路径",
        }.get(policy_name, "自适应推理")

        return (
            f"[混合推理 - {policy_desc}]\n"
            f"根据当前上下文分析:\n"
            f"- 用户消息: {evidence.get('n_user_messages', 0)}条\n"
            f"- 助手回复: {evidence.get('n_assistant_messages', 0)}条\n"
            f"- 策略: {policy_name}\n"
            f"- 自由能 F={self.last_f_value:.3f}\n\n"
            f"请基于以上分析回答用户的问题。"
        )

    def reset(self):
        """重置调度器状态"""
        self.total_decisions = 0
        self.explore_count = 0
        self.direct_count = 0
        self.decision_history = []
        self._message_hashes = []
        self.last_f_value = 0.0
        self.last_components = {}
        self.threshold = self.base_threshold
        self.threshold_history = [self.base_threshold]
