"""
渐进式上下文管理 — ProgressiveContextManager

对抗上下文膨胀的分级策略:
- 50%→warning: 摘要最旧消息
- 70%→engaged: 激进压缩
- 85%→stressed: 截断中间
- 90%→critical: 建议新会话 + 迁移关键记忆
"""
import hashlib
from typing import List, Dict, Optional
from collections import deque


class ProgressiveContextManager:
    """分级上下文管理器"""

    LEVELS = {
        "optimal":  50,   # 0-50%
        "warning":  70,   # 50-70%
        "engaged":  85,   # 70-85%
        "stressed": 90,   # 85-90%
        "critical": 100,  # 90%+
    }

    ACTIONS = {
        "optimal":  "none",
        "warning":  "summarize_oldest",
        "engaged":  "aggressive_compress",
        "stressed": "truncate_middle",
        "critical": "suggest_new_session",
    }

    def __init__(self, max_tokens: int = 16000):
        self.max_tokens = max_tokens
        self.level_history: deque = deque(maxlen=20)
        self.current_level = "optimal"
        self._consecutive_critical = 0
        self._critical_memory_bank: List[Dict] = []

    # ── 级别判断 ──────────────────────────────

    def get_level(self, current_tokens: int) -> str:
        pct = (current_tokens / self.max_tokens) * 100
        for level, threshold in self.LEVELS.items():
            if pct <= threshold:
                return level
        return "critical"

    def get_action(self, level: str) -> str:
        return self.ACTIONS.get(level, "none")

    def record_level(self, level: str):
        self.level_history.append(level)
        self.current_level = level
        if level == "critical":
            self._consecutive_critical += 1
        else:
            self._consecutive_critical = 0

    def should_suggest_new_session(self) -> bool:
        return self._consecutive_critical >= 3

    # ── Token估算 ─────────────────────────────

    def estimate_tokens(self, text: str) -> int:
        """粗略估算: 中文~1.5 char/token, 英文~4 char/token"""
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4)

    # ── 压缩策略 ──────────────────────────────

    def compress(self, messages: List[Dict], level: str) -> List[Dict]:
        """根据级别压缩消息列表"""
        if len(messages) <= 3:
            return messages

        if level in ("optimal",):
            return messages

        if level == "warning":
            return self._summarize_oldest(messages)

        if level == "engaged":
            return self._aggressive_compress(messages)

        if level in ("stressed", "critical"):
            return self._truncate_middle(messages)

        return messages

    def _summarize_oldest(self, messages: List[Dict]) -> List[Dict]:
        """摘要最旧的30%消息"""
        split = max(1, len(messages) // 3)
        old = messages[:split]
        rest = messages[split:]

        summary = self._make_summary(old)
        return [{"role": "system", "content": f"[前{len(old)}条对话摘要]: {summary}"}] + rest

    def _aggressive_compress(self, messages: List[Dict]) -> List[Dict]:
        """保留首2+尾5，中间摘要"""
        if len(messages) <= 10:
            return self._summarize_oldest(messages)

        head = messages[:2]
        tail = messages[-5:]
        middle = messages[2:-5]

        summary = self._make_summary(middle)
        return head + [
            {"role": "system", "content": f"[中间{len(middle)}条摘要]: {summary}"}
        ] + tail

    def _truncate_middle(self, messages: List[Dict]) -> List[Dict]:
        """激进截断: 只保留首2+尾3"""
        if len(messages) <= 7:
            return messages

        head = messages[:2]
        tail = messages[-3:]
        middle_count = len(messages) - 5

        return head + [
            {"role": "system", "content": f"[已截断{middle_count}条历史消息]"}
        ] + tail

    def _make_summary(self, messages: List[Dict]) -> str:
        """生成简单摘要（不调LLM，规则化）"""
        user_msgs = [m["content"][:80] for m in messages if m["role"] == "user"]
        topics = set()
        for msg in user_msgs:
            for word in msg.split():
                if len(word) > 2:
                    topics.add(word)
        return f"讨论主题: {', '.join(list(topics)[:10])}"

    # ── 记忆迁移 ──────────────────────────────

    def extract_critical(self, messages: List[Dict]) -> List[Dict]:
        """提取关键记忆供新会话使用"""
        critical = []

        for m in messages:
            content = m.get("content", "")
            role = m.get("role", "")

            # 保留系统提示
            if role == "system":
                critical.append(m)
                continue

            # 保留用户的事实陈述（包含路径、配置等）
            if role == "user":
                if any(kw in content.lower() for kw in [
                    "项目在", "project", "路径", "path",
                    "api key", "配置", "config", "版本",
                    "我的", "用户名", "端口", "地址",
                ]):
                    critical.append(m)

        # 加入已存储的关键记忆
        for mem in self._critical_memory_bank[-5:]:
            critical.append({"role": "system", "content": f"[关键记忆]: {mem['content']}"})

        return critical

    def store_critical_memory(self, content: str):
        """手动存储关键记忆（跨会话保留）"""
        self._critical_memory_bank.append({
            "content": content,
            "fingerprint": hashlib.md5(content.encode()).hexdigest()[:8],
        })

    def get_critical_memories(self) -> List[Dict]:
        return list(self._critical_memory_bank)
