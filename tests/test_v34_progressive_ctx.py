"""
分级上下文管理测试 — ProgressiveContextManager
"""
import pytest


class TestProgressiveContext:
    """渐进式上下文压缩"""

    def test_initial_level_is_optimal(self):
        from src.core.progressive_context import ProgressiveContextManager
        pcm = ProgressiveContextManager(max_tokens=16000)
        assert pcm.current_level == "optimal"

    def test_level_transitions(self):
        """50%→warning, 70%→engaged, 85%→stressed, 90%→critical"""
        from src.core.progressive_context import ProgressiveContextManager
        pcm = ProgressiveContextManager(max_tokens=10000)

        assert pcm.get_level(4000) == "optimal"      # 40%
        assert pcm.get_level(5500) == "warning"       # 55%
        assert pcm.get_level(7500) == "engaged"       # 75%
        assert pcm.get_level(8800) == "stressed"      # 88%
        assert pcm.get_level(9200) == "critical"      # 92%

    def test_action_for_each_level(self):
        """每个级别有对应动作"""
        from src.core.progressive_context import ProgressiveContextManager
        pcm = ProgressiveContextManager(max_tokens=10000)

        actions = {
            "optimal":  "none",
            "warning":  "summarize_oldest",
            "engaged":  "aggressive_compress",
            "stressed": "truncate_middle",
            "critical": "suggest_new_session",
        }
        for level, expected in actions.items():
            assert pcm.get_action(level) == expected

    def test_suggest_new_session_at_critical(self):
        """90%以上连续出现建议新会话"""
        from src.core.progressive_context import ProgressiveContextManager
        pcm = ProgressiveContextManager(max_tokens=10000)

        assert not pcm.should_suggest_new_session()
        pcm.record_level("critical")
        assert not pcm.should_suggest_new_session()
        pcm.record_level("critical")
        assert not pcm.should_suggest_new_session()
        pcm.record_level("critical")
        assert pcm.should_suggest_new_session()

    def test_extract_critical_memories(self):
        """从历史中提取关键记忆迁移到新会话"""
        from src.core.progressive_context import ProgressiveContextManager
        pcm = ProgressiveContextManager(max_tokens=10000)

        messages = [
            {"role": "system", "content": "你是meshctx"},
            {"role": "user", "content": "帮我写代码"},
            {"role": "assistant", "content": "好的..."},
            {"role": "user", "content": "我的项目在/home/project"},
            {"role": "assistant", "content": "了解"},
            {"role": "user", "content": "API Key是sk-abc"},
        ]
        critical = pcm.extract_critical(messages)
        # 应保留系统提示、用户事实陈述
        assert len(critical) >= 2

    def test_compress_middle_messages(self):
        """压缩中间消息为摘要"""
        from src.core.progressive_context import ProgressiveContextManager
        pcm = ProgressiveContextManager(max_tokens=10000)

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "msg1" * 100},
            {"role": "assistant", "content": "reply1" * 100},
            {"role": "user", "content": "msg2" * 100},
            {"role": "assistant", "content": "reply2" * 100},
            {"role": "user", "content": "latest"},
        ]
        compressed = pcm.compress(messages, level="engaged")
        # 保留首尾，中间压缩
        assert len(compressed) < len(messages)
        assert compressed[0]["role"] == "system"  # 系统提示保留
        assert compressed[-1]["role"] == "user"    # 最新消息保留

    def test_token_estimation(self):
        """估算token数"""
        from src.core.progressive_context import ProgressiveContextManager
        pcm = ProgressiveContextManager()

        text = "Hello world" * 100
        tokens = pcm.estimate_tokens(text)
        assert tokens > 0
        assert tokens < len(text)  # tokens < chars
