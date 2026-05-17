"""
上下文自动压缩 (Context Compressor)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
当Agent的上下文窗口超过阈值时自动压缩，保留：
1. 系统提示词 (不可压)
2. 关键原则 (不可压)
3. 最近的N条消息 (保留最新)
4. 中间消息的摘要 (LLM自动压缩)

设计灵感: 海马体的记忆巩固 → 将详细情景记忆压缩为语义摘要
对标: hermes-agent的自动context compression (compress/compressor模块)
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ContextCompressor:
    """上下文压缩器 — 海马体式记忆巩固
    
    触发条件: 上下文 tokens > threshold 时自动执行
    保留策略:
      - 首部: 系统消息 + 原则 (永远保留)
      - 中部: 压缩为摘要 (LLM调用)
      - 尾部: 最近N条消息 (保留完整)
    """

    # 触发阈值 (tokens)
    DEFAULT_THRESHOLD = 8000      # 上下文tokens > 此值时触发
    TARGET_RATIO = 0.40            # 压缩后目标占原比例
    KEEP_LAST = 10                 # 保留最近N条消息
    
    def __init__(self, threshold: int = DEFAULT_THRESHOLD, keep_last: int = KEEP_LAST):
        self.threshold = threshold
        self.keep_last = keep_last
        self.target_ratio = self.TARGET_RATIO
        self._stats: Dict[str, Any] = {
            "compressions": 0,
            "total_tokens_saved": 0,
            "last_compression_time": 0,
        }

    def should_compress(self, estimated_tokens: int) -> bool:
        """判断是否需要压缩"""
        return estimated_tokens > self.threshold

    def compress(self, messages: List[Dict[str, str]], 
                 system_prompt: str = "",
                 principles: str = "") -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
        """压缩消息列表
        
        Args:
            messages: 完整消息列表 [{role, content}, ...]
            system_prompt: 系统提示词 (不可压缩)
            principles: 关键原则 (不可压缩, 注入到压缩后首部)
            
        Returns:
            (compressed_messages, compression_info)
        """
        if len(messages) <= self.keep_last + 4:
            # 消息太少，不需要压缩
            return messages, {"action": "skipped", "reason": "too_few_messages"}

        start_time = time.time()
        original_count = len(messages)
        
        # 估算原始tokens (粗略: 1 token ≈ 3.5 chars for mixed Chinese/English)
        original_tokens = sum(len(m.get("content", "")) for m in messages) // 3

        # 策略: 保留首部(系统+原则) 和 尾部(最近N条)
        # 中部生成摘要
        
        middle_start = 1  # Skip system message at index 0
        if principles:
            middle_start = 2  # Skip principles too
        
        tail_start = max(middle_start, original_count - self.keep_last)
        
        # 中部需要压缩的消息
        middle_messages = messages[middle_start:tail_start]
        
        if not middle_messages:
            return messages, {"action": "skipped", "reason": "no_middle_messages"}
        
        # 生成压缩摘要
        summary = self._generate_summary(middle_messages, principles)
        
        # 构建压缩后的消息列表
        compressed = []
        
        # 1. 系统消息
        if messages[0].get("role") == "system":
            compressed.append(messages[0])
        
        # 2. 原则 (如果有)
        if principles:
            compressed.append({
                "role": "system",
                "content": f"## ⚠️ 核心原则 (始终有效)\n{principles}\n\n> 以下为对话历史摘要："
            })
        
        # 3. 压缩摘要
        compressed.append({
            "role": "system",
            "content": f"[上下文压缩 {time.strftime('%H:%M:%S')}] "
                      f"以下为前 {len(middle_messages)} 条消息的摘要:\n{summary}"
        })
        
        # 4. 尾部最新消息
        compressed.extend(messages[tail_start:])
        
        compressed_tokens = sum(len(m.get("content", "")) for m in compressed) // 3
        tokens_saved = original_tokens - compressed_tokens
        
        self._stats["compressions"] += 1
        self._stats["total_tokens_saved"] += tokens_saved
        self._stats["last_compression_time"] = time.time()
        
        info = {
            "action": "compressed",
            "original_count": original_count,
            "compressed_count": len(compressed),
            "original_tokens_est": original_tokens,
            "compressed_tokens_est": compressed_tokens,
            "tokens_saved": tokens_saved,
            "ratio": round(compressed_tokens / max(original_tokens, 1), 3),
            "duration_ms": round((time.time() - start_time) * 1000),
        }
        
        logger.info(
            f"[COMPRESS] {original_count}→{len(compressed)} msgs, "
            f"{original_tokens}→{compressed_tokens} tokens, "
            f"saved {tokens_saved} tokens ({info['ratio']:.0%})"
        )
        
        return compressed, info

    def _generate_summary(self, messages: List[Dict[str, str]], 
                          principles: str = "") -> str:
        """生成消息摘要 (规则化版本, 不依赖LLM调用)
        
        实际生产环境中，这里应调用LLM进行语义摘要。
        规则化版本作为fallback，提取关键信息。
        """
        parts = []
        user_count = 0
        assistant_count = 0
        tool_count = 0
        
        topics = []
        errors = []
        
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            
            if role == "user":
                user_count += 1
                # 提取前80字符作为话题
                if len(content) > 10:
                    topics.append(content[:80].strip())
            elif role == "assistant":
                assistant_count += 1
                # 检测错误
                if "error" in content.lower() or "失败" in content:
                    errors.append(content[:100].strip())
            elif role == "tool" or role == "function":
                tool_count += 1
        
        lines = []
        lines.append(f"共 {len(messages)} 条消息")
        lines.append(f"- 用户消息: {user_count} 条")
        lines.append(f"- AI回复: {assistant_count} 条")
        lines.append(f"- 工具调用: {tool_count} 次")
        
        if topics:
            lines.append(f"\n主要话题:")
            for t in topics[:5]:
                lines.append(f"  • {t}")
        
        if errors:
            lines.append(f"\n⚠️ 遇到的错误:")
            for e in errors[:3]:
                lines.append(f"  • {e}")
        
        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "threshold": self.threshold,
            "keep_last": self.keep_last,
            "target_ratio": self.target_ratio,
        }

    def reset_stats(self):
        self._stats = {
            "compressions": 0,
            "total_tokens_saved": 0,
            "last_compression_time": 0,
        }


# 单例
_compressor_instance: Optional[ContextCompressor] = None


def get_compressor(threshold: int = 8000) -> ContextCompressor:
    """获取ContextCompressor单例"""
    global _compressor_instance
    if _compressor_instance is None:
        _compressor_instance = ContextCompressor(threshold=threshold)
    return _compressor_instance
