"""
Prefrontal Cortex (PFC) — 前额叶皮层
=====================================
核心功能:
  WorkingMemory    — N-back 工作记忆 (Goldman-Rakic 1995)
  TaskSwitcher     — 任务切换/执行控制 (Miller & Cohen 2001)
  SimplePlanner    — 前向规划 (Shallice 1982)

参考:
  Goldman-Rakic PS. "Cellular basis of working memory." Neuron, 1995
  Miller EK, Cohen JD. "An integrative theory of PFC function." Annu Rev Neurosci, 2001
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from collections import deque


@dataclass
class WMItem:
    """Working memory chunk — capacity-limited, decay-prone."""
    content: str
    embedding: np.ndarray
    priority: float = 0.5       # attentional priority
    decay: float = 1.0          # activation (1.0 = full, decays over time)
    created_at: int = 0


@dataclass
class PlanStep:
    action: str
    expected_outcome: str
    confidence: float


class WorkingMemory:
    """PFC dorsolateral — maintains ~4±1 chunks with active rehearsal."""

    def __init__(self, capacity: int = 4, embedding_dim: int = 64, decay_rate: float = 0.03):
        self.capacity = capacity
        self.embedding_dim = embedding_dim
        self.decay_rate = decay_rate
        self.items: List[WMItem] = []
        self._step = 0

    def _embed(self, text: str) -> np.ndarray:
        """语义嵌入 — 优先使用 sentence-transformers，回退到 TF-IDF/hash."""
        # 尝试 sentence-transformers (真实语义)
        if not hasattr(self, '_encoder'):
            try:
                from sentence_transformers import SentenceTransformer
                self._encoder = SentenceTransformer('all-MiniLM-L6-v2')
                self._encode_fn = lambda t: self._encoder.encode([t])[0]
            except ImportError:
                # 回退: sklearn TfidfVectorizer (有语义但不完美)
                try:
                    from sklearn.feature_extraction.text import TfidfVectorizer
                    self._tfidf = TfidfVectorizer(max_features=self.embedding_dim)
                    self._tfidf.fit([text])  # 在线学习
                    self._encode_fn = lambda t: self._tfidf.transform([t]).toarray()[0][:self.embedding_dim]
                except ImportError:
                    # 最后回退: 确定性 hash (至少跨进程一致)
                    import hashlib
                    self._encode_fn = lambda t: np.array(
                        [float(ord(c))/128.0 for c in hashlib.sha256(t.encode()).hexdigest()[:self.embedding_dim*2]]
                    )[:self.embedding_dim]
        
        vec = self._encode_fn(text)
        # pad or truncate
        if len(vec) < self.embedding_dim:
            vec = np.pad(vec, (0, self.embedding_dim - len(vec)))
        return np.array(vec[:self.embedding_dim], dtype=float)

    def store(self, content: str, priority: float = 0.5) -> Optional[WMItem]:
        emb = self._embed(content)
        # Check for duplicates
        for item in self.items:
            if np.dot(emb, item.embedding) / (np.linalg.norm(emb) * np.linalg.norm(item.embedding) + 1e-8) > 0.9:
                item.priority = max(item.priority, priority)
                item.decay = 1.0
                return item

        item = WMItem(content=content, embedding=emb, priority=priority, created_at=self._step)

        if len(self.items) < self.capacity:
            self.items.append(item)
        else:
            # Evict lowest priority*decay item
            scores = [(i, it.priority * it.decay) for i, it in enumerate(self.items)]
            scores.sort(key=lambda x: x[1])
            self.items[scores[0][0]] = item

        return item

    def recall(self, cue: str, top_k: int = 2) -> List[Tuple[WMItem, float]]:
        cue_emb = self._embed(cue)
        scored = []
        for item in self.items:
            sim = float(np.dot(cue_emb, item.embedding) /
                        (np.linalg.norm(cue_emb) * np.linalg.norm(item.embedding) + 1e-8))
            scored.append((item, sim * item.decay * item.priority))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    def rehearse(self):
        """Active maintenance — boost decay of all items (phonological loop)."""
        for item in self.items:
            item.decay = min(1.0, item.decay + 0.05)

        # Remove fully decayed items
        self.items = [it for it in self.items if it.decay > 0.1]

    def step(self):
        """Apply time-based decay."""
        self._step += 1
        for item in self.items:
            item.decay = max(0.0, item.decay - self.decay_rate * (1.0 - item.priority * 0.5))

        # Garbage collect
        self.items = [it for it in self.items if it.decay > 0.05]

    def load(self) -> int:
        """Current WM load."""
        return len(self.items)

    def mean_decay(self) -> float:
        if not self.items:
            return 0.0
        return float(np.mean([it.decay for it in self.items]))


class TaskSwitcher:
    """PFC ventrolateral — task-set switching with switch cost (Monsell 2003)."""

    def __init__(self, n_rules: int = 4):
        self.n_rules = n_rules
        self.current_rule = 0
        self.rule_weights = np.ones(n_rules) / n_rules
        self.switch_cost = 0.0  # accumulates, decays
        self.total_switches = 0
        self._recent_errors: deque = deque(maxlen=20)

    def switch_to(self, rule_idx: int) -> float:
        """Switch to a new task rule. Returns switch cost."""
        if rule_idx == self.current_rule:
            self.switch_cost = max(0.0, self.switch_cost - 0.1)
            return 0.0

        cost = 0.15 + self.switch_cost
        self.switch_cost = min(0.5, self.switch_cost + 0.1)
        self.current_rule = rule_idx
        self.total_switches += 1
        return cost

    def select_rule(self, context: np.ndarray) -> Tuple[int, float]:
        """Select the best rule given context features."""
        scores = np.dot(self.rule_weights, context[:self.n_rules])
        rule = int(np.argmax(np.abs(self.rule_weights * context[:self.n_rules])))
        return rule, float(scores)

    def update(self, rule_idx: int, error: float):
        """Update rule weights based on outcome."""
        lr = 0.1
        self.rule_weights[rule_idx] = max(0.01, self.rule_weights[rule_idx] - error * lr)
        self.rule_weights = self.rule_weights / self.rule_weights.sum()
        self._recent_errors.append(error)

    def mean_error(self) -> float:
        if not self._recent_errors:
            return 0.0
        return float(np.mean(self._recent_errors))


class SimplePlanner:
    """PFC rostral — basic forward planning (depth-limited search)."""

    def __init__(self, max_depth: int = 3):
        self.max_depth = max_depth
        self.plans_made = 0

    def plan(self, state: str, actions: List[str],
             transition_fn, goal_fn, depth: int = 0) -> List[PlanStep]:
        """Simple recursive forward planner."""
        if depth >= self.max_depth:
            return []

        best_plan = []
        best_score = -1

        for action in actions:
            next_state = transition_fn(state, action)
            score = goal_fn(next_state)

            sub_plan = self.plan(next_state, actions, transition_fn, goal_fn, depth + 1)
            total_score = score + sum(s.confidence for s in sub_plan) * 0.5

            if total_score > best_score:
                best_score = total_score
                best_plan = [PlanStep(action=action,
                                      expected_outcome=str(next_state)[:40],
                                      confidence=score)] + sub_plan

        self.plans_made += 1
        return best_plan
