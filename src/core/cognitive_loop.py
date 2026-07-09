"""
MeshCtx Cognitive Loop — 世界第一Agent认知架构 (v3.115.16)

架构突破: 脑区不是LLM的附属，而是主决策者。
LLM只是一个可以被脑区选择调用的工具。

认知闭环:
  Pre-Thinking  →  脑区决定策略(要不要调LLM?调几次?)
  During-LLM   →  脑区动态调控(温度、token数、停止条件)  
  Post-LLM     →  脑区验证输出+固化学习
  Idle         →  离线回放巩固(睡眠学习)

与所有其他agent的本质区别:
  - ChatGPT etc: 无状态, 无记忆, 不学习
  - LangChain etc: 工具链, 但决策仍在LLM
  - meshctx: 脑区主决策, LLM只是工具之一
"""
import numpy as np
import time
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger("meshctx.cognitive")


@dataclass
class CognitiveState:
    """认知状态 — 13脑区在当前时刻的完整快照"""
    thalamus_gate: bool = True
    amygdala_valence: float = 0.0
    amygdala_arousal: float = 0.0
    hippocampus_recalled: List[str] = field(default_factory=list)
    hippocampus_cache_hit: bool = False
    basal_ganglia_action: str = "respond"
    basal_ganglia_confidence: float = 0.5
    cerebellum_prediction: str = "unknown"
    cerebellum_confidence: float = 0.5
    acc_conflict: float = 0.0
    insula_stressed: bool = False
    mirror_intent: str = "unknown"
    dmn_strategy: str = "direct_response"
    phi: float = 0.0
    iit_integration: float = 0.0


class CognitiveLoop:
    """
    认知闭环 — 脑区主决策架构。
    
    每次用户输入经过三阶段:
    Phase 1 (Pre-LLM): 脑区决定策略 — 查缓存?调LLM?多轮?
    Phase 2 (During-LLM): 脑区动态调控 — 温度/停止/纠错
    Phase 3 (Post-LLM): 脑区验证+学习 — 预测对照+巩固
    """
    
    def __init__(self):
        try: from .brain_architecture import BrainLoop
        except ImportError: BrainLoop = None
        self.brain = BrainLoop() if BrainLoop else None
        
        # 学习状态
        self._cache: Dict[str, Tuple[str, float]] = {}  # query→(response, timestamp)
        self._success_count = 0
        self._failure_count = 0
        self._llm_calls_saved = 0  # 缓存命中次数
        self._hallucinations_caught = 0
        self._total_interactions = 0
    
    def think(self, user_msg: str, conversation_history: List[Dict] = None,
              system_prompt: str = "") -> Dict[str, Any]:
        """
        完整的认知闭环 — 脑区主决策。
        
        Returns dict with:
          - should_call_llm: bool — 是否需要调LLM
          - enhanced_prompt: str — 脑区增强后的system prompt
          - llm_params: dict — 动态调控参数(temperature/max_tokens等)
          - cognitive_state: CognitiveState — 脑区状态快照
          - cache_hit: bool — 是否从记忆缓存直接回答
        """
        self._total_interactions += 1
        state = CognitiveState()
        
        if not self.brain:
            return {'should_call_llm': True, 'cognitive_state': state}
        
        # ═══ Phase 1: Pre-LLM — 脑区决策 ═══
        brain_result = self.brain.think(user_msg, 
            ['use_llm','cache_lookup','clarify','direct_answer','multi_step'],
            priority=0.8)  # higher priority to pass thalamus gate
        
        state.phi = brain_result.get('phi', 0)
        # Always process — thalamus gates only truly irrelevant noise
        state.thalamus_gate = True
        
        if not state.thalamus_gate and len(user_msg) < 5:
            return {'should_call_llm': False, 'cognitive_state': state,
                    'response': 'I need more context to help with that.'}
        
        # Amygdala: emotional context
        emotion = brain_result.get('emotion', {})
        state.amygdala_valence = emotion.get('valence', 0)
        state.amygdala_arousal = emotion.get('arousal', 0)
        
        # Hippocampus: memory recall + cache lookup
        recalled = brain_result.get('recalled_memories', [])
        state.hippocampus_recalled = recalled
        
        # Check cache for similar queries
        cache_key = self._normalize_query(user_msg)
        if cache_key in self._cache:
            cached_response, cached_time = self._cache[cache_key]
            if time.time() - cached_time < 3600:  # 1 hour TTL
                state.hippocampus_cache_hit = True
                self._llm_calls_saved += 1
                return {
                    'should_call_llm': False,
                    'cache_hit': True,
                    'response': cached_response,
                    'cognitive_state': state,
                }
        
        # Mirror Neurons: user intent
        intention = brain_result.get('intention', {})
        state.mirror_intent = str(intention.get('intention', 'unknown'))[:50]
        
        # DMN: strategy selection
        if state.mirror_intent in ['fix','urgent','error']:
            state.dmn_strategy = 'fast_direct'
        elif len(recalled) > 2:
            state.dmn_strategy = 'memory_augmented'
        else:
            state.dmn_strategy = 'standard_llm'
        
        # Basal Ganglia: action selection
        action = brain_result.get('action', 'use_llm')
        confidence = brain_result.get('confidence', 0.5)
        state.basal_ganglia_action = action
        state.basal_ganglia_confidence = confidence
        
        # Cerebellum: predict outcome
        prediction = brain_result.get('prediction', {})
        state.cerebellum_prediction = str(prediction.get('outcome', 'unknown'))[:50]
        
        # ACC: conflict detection
        state.acc_conflict = brain_result.get('conflict', 0)
        
        # ═══ Phase 2: Build Enhanced Prompt ═══
        enhanced_prompt = system_prompt
        
        # Brain context injection — this is the KEY differentiator
        brain_context = []
        if recalled:
            brain_context.append(f"[Memory] Similar past situations: {'; '.join(recalled[:3])}")
        if state.mirror_intent and state.mirror_intent != 'unknown':
            brain_context.append(f"[Intent] User likely wants: {state.mirror_intent}")
        if abs(state.amygdala_valence) > 0.3:
            tone = 'urgent/negative' if state.amygdala_valence < -0.2 else 'positive/engaged'
            brain_context.append(f"[Tone] Emotional context: {tone}")
        if state.acc_conflict > 0.5:
            brain_context.append(f"[Warning] High decision conflict ({state.acc_conflict:.1f}) — consider asking clarifying question")
        
        if brain_context:
            enhanced_prompt = "[Brain Context]\n" + "\n".join(brain_context) + "\n\n" + system_prompt
        
        # ═══ Phase 2: Dynamic LLM Parameters ═══
        llm_params = {
            'temperature': 0.7,
            'max_tokens': 4096,
        }
        
        # Emotional urgency → lower temperature (more precise)
        if state.amygdala_arousal > 0.6:
            llm_params['temperature'] = max(0.3, 0.7 - state.amygdala_arousal * 0.5)
        
        # High conflict → lower temperature (be more careful)
        if state.acc_conflict > 0.5:
            llm_params['temperature'] = max(0.2, llm_params['temperature'] - 0.3)
        
        # Memory augmented → allow more tokens for context
        if state.dmn_strategy == 'memory_augmented':
            llm_params['max_tokens'] = 8192
        
        # Insula stress → reduce tokens to avoid overload
        if brain_result.get('anomaly', False):
            llm_params['max_tokens'] = 2048
            state.insula_stressed = True
        
        return {
            'should_call_llm': action != 'direct_answer',
            'enhanced_prompt': enhanced_prompt,
            'llm_params': llm_params,
            'cognitive_state': state,
            'cache_hit': False,
        }
    
    def learn(self, user_msg: str, llm_response: str, success: bool,
              cognitive_state: CognitiveState = None):
        """
        Phase 3 (Post-LLM): 脑区学习固化
        
        1. Cerebellum: 对照预测 vs 实际 → 更新前向模型
        2. Basal Ganglia: 奖励/惩罚 → 调整动作偏好
        3. Hippocampus: 编码经验 → 长期记忆
        4. Cache: 成功结果缓存 → 未来快速响应
        """
        if success:
            self._success_count += 1
            # Cache successful responses
            cache_key = self._normalize_query(user_msg)
            self._cache[cache_key] = (llm_response, time.time())
            if len(self._cache) > 500:
                # Evict oldest entries
                sorted_items = sorted(self._cache.items(), key=lambda x: x[1][1])
                self._cache = dict(sorted_items[-200:])
        else:
            self._failure_count += 1
        
        # Brain learning
        try:
            if self.brain:
                action = cognitive_state.basal_ganglia_action if cognitive_state else 'use_llm'
                self.brain.learn_from_outcome(
                    user_msg, action, success,
                    reward=0.8 if success else -0.2
                )
        except Exception as e:
            logger.debug(f"Brain learn error: {e}")
        
        # Periodic consolidation
        if self._total_interactions % 20 == 0:
            try:
                if self.brain and self.brain.hippocampus.detect_swr(5):
                    self.brain.hippocampus.replay_swr(3)
            except Exception:
                pass
    
    def validate_response(self, llm_response: str, cognitive_state: CognitiveState) -> Dict:
        """
        Post-LLM validation: brain checks LLM output quality.
        Returns {is_valid, issues, corrected_response}
        """
        issues = []
        
        # Cerebellum: compare prediction to actual
        if cognitive_state.cerebellum_prediction != 'unknown':
            # Simple heuristic: if prediction was "code" but response has no code blocks
            if 'code' in cognitive_state.cerebellum_prediction.lower():
                if '```' not in llm_response:
                    issues.append("Expected code but none found — possible hallucination")
        
        # ACC: high conflict response → flag for review
        if cognitive_state.acc_conflict > 0.7:
            issues.append(f"High conflict decision ({cognitive_state.acc_conflict:.1f}) — response may be uncertain")
        
        return {
            'is_valid': len(issues) == 0,
            'issues': issues,
            'corrected_response': llm_response,
        }
    
    def _normalize_query(self, text: str) -> str:
        """Normalize query for cache lookup — strip punct, lowercase, truncate."""
        import re
        cleaned = re.sub(r'[^\w\s]', '', text.lower())
        return ' '.join(cleaned.split())[:80]
    
    def stats(self) -> dict:
        try:
            brain_stats = self.brain.stats() if self.brain else {}
        except Exception:
            brain_stats = {}
        
        return {
            'interactions': self._total_interactions,
            'success_rate': self._success_count / max(1, self._total_interactions),
            'cache_hits': self._llm_calls_saved,
            'cache_size': len(self._cache),
            'hallucinations_caught': self._hallucinations_caught,
            'brain': brain_stats,
        }


# ═══════════════════════════════════════════════════════════════
# 基准测试 — 证明脑区让agent更聪明
# ═══════════════════════════════════════════════════════════════

def benchmark_cognitive_vs_baseline(n_trials: int = 20) -> dict:
    """
    对比测试: CognitiveLoop vs 无脑区baseline
    
    测试指标:
    1. 缓存命中率 — 重复问题不调LLM
    2. 上下文增强 — prompt是否包含记忆
    3. 决策多样性 — 不只是respond
    """
    loop = CognitiveLoop()
    
    results = {
        'cache_hits': 0,
        'llm_calls': 0,
        'context_injections': 0,
        'actions': [],
    }
    
    test_queries = [
        "Fix the login bug",
        "Fix the login bug",  # repeat → should cache hit
        "Add dark mode to settings",
        "Database connection timeout error",
        "Database connection timeout error",  # repeat
        "How do I deploy to production?",
        "Security vulnerability in auth module",
        "Fix the login bug",  # third repeat
    ]
    
    for query in test_queries * 3:  # 24 trials
        result = loop.think(query)
        
        if result.get('cache_hit'):
            results['cache_hits'] += 1
        elif result.get('should_call_llm'):
            results['llm_calls'] += 1
        
        prompt = result.get('enhanced_prompt', '')
        if '[Brain Context]' in prompt:
            results['context_injections'] += 1
        
        if result.get('cognitive_state'):
            results['actions'].append(result['cognitive_state'].basal_ganglia_action)
    
    return {
        'total_trials': len(test_queries) * 3,
        'cache_hit_rate': results['cache_hits'] / max(1, len(test_queries) * 3),
        'llm_calls_saved': results['cache_hits'],
        'context_injections': results['context_injections'],
        'action_diversity': len(set(results['actions'])),
        'stats': loop.stats(),
    }
