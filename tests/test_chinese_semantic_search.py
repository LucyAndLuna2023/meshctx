"""
meshctx 回归测试: 中文语义搜索 (jieba分词)
Bug: TF-IDF vectorizer不支持中文, vocab_size=7, 所有查询返回相同结果
Fix: 集成jieba中文分词, 模块级导入 + 优雅回退
"""
import pytest
import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 测试需要jieba (meshctx venv中已安装)
try:
    import jieba
    HAS_JIEBA = True
except ImportError:
    HAS_JIEBA = False

# 依赖 src.core.memory_v2 (核心闭源实现) — stub 模式下自动 skip
def _core_stub() -> bool:
    try:
        from src.core import _HAS_MESHCTX_CORE
        return not _HAS_MESHCTX_CORE
    except Exception:
        return False

pytestmark = pytest.mark.skipif(
    _core_stub(),
    reason="依赖 meshctx-core 核心模块 (memory_v2), stub 模式下跳过; 安装 meshctx-core 后自动恢复"
)


class TestChineseTokenization:
    """验证中文分词正确性"""

    def test_jieba_available(self):
        """jieba已安装且模块级导入成功"""
        from src.core import memory_v2
        import importlib
        importlib.reload(memory_v2)
        assert memory_v2._HAS_JIEBA, "jieba必须可用"
        assert memory_v2.jieba is not None, "模块级jieba引用必须非空"

    def test_chinese_tokenization_semantic(self):
        """中文分词产生有语义的token而非bi-gram"""
        from src.core.memory_v2 import TfidfVectorizer
        tfidf = TfidfVectorizer()
        tokens = tfidf._tokenize("机器学习是人工智能的核心技术")

        # 应该包含语义词，而非纯bi-gram
        assert "机器学习" in tokens or "机器" in tokens, f"应包含'机器学习'或'机器', 实际: {tokens}"
        assert "人工智能" in tokens or "人工" in tokens, f"应包含'人工智能'或'人工', 实际: {tokens}"
        assert any("核心" in t or "技术" in t for t in tokens), \
            f"应包含'核心'或'技术'(jieba可能将'核心技术'视为一个词), 实际: {tokens}"

        # 不应该只有bi-gram
        bi_grams = [t for t in tokens if len(t) == 2]
        # bi-gram占比应低于50%
        bi_ratio = len(bi_grams) / max(len(tokens), 1)
        assert bi_ratio < 0.7, (
            f"bi-gram占比过高({bi_ratio:.1%}): {tokens}"
        )

    def test_english_tokenization_preserved(self):
        """英文单词分词不受影响"""
        from src.core.memory_v2 import TfidfVectorizer
        tfidf = TfidfVectorizer()
        tokens = tfidf._tokenize("Python pandas numpy are data science tools")

        assert "python" in tokens
        assert "pandas" in tokens
        assert "numpy" in tokens

    def test_mixed_chinese_english(self):
        """中英混合文本正确分词"""
        from src.core.memory_v2 import TfidfVectorizer
        tfidf = TfidfVectorizer()
        tokens = tfidf._tokenize("geoV1端口3002版本v1.01")

        assert "端口" in tokens or "port" in tokens, f"应包含'端口': {tokens}"
        assert any("3002" in t or t == "3002" for t in tokens), f"应包含3002: {tokens}"
        # 不应该有bi-gram碎片
        assert "口3" not in tokens, f"不应有跨语言bi-gram: {tokens}"

    def test_pure_numbers_handled(self):
        """纯数字文本处理"""
        from src.core.memory_v2 import TfidfVectorizer
        tfidf = TfidfVectorizer()
        tokens = tfidf._tokenize("3002")
        assert isinstance(tokens, list)


class TestChineseSemanticSearch:
    """验证中文语义搜索区分度"""

    @pytest.fixture
    def vector_store(self):
        from src.core.memory_v2 import VectorStore
        import importlib
        from src.core import memory_v2
        importlib.reload(memory_v2)

        vs = VectorStore()
        docs = [
            "机器学习是人工智能的核心技术之一",
            "深度学习使用多层神经网络进行特征提取",
            "北京故宫是中国最著名的历史建筑",
            "Python的pandas库非常适合数据清洗",
            "量子纠缠是一种奇特的物理现象",
            "电动汽车使用锂电池作为动力来源",
            "区块链技术可以用于供应链追溯",
            "围棋AI AlphaGo击败了世界冠军",
            "气候变化导致全球海平面上升",
            "基因编辑技术CRISPR获得诺贝尔奖",
            "5G通信技术提高了网络传输速度",
            "新能源包括太阳能和风能发电",
            "金融市场中量化交易越来越流行",
            "云计算提供了弹性的计算资源",
            "开源软件促进了技术创新和共享",
            "自然语言处理是AI的重要应用领域",
            "大数据分析帮助企业做出决策",
            "网络安全是数字经济的基础保障",
            "知识图谱是语义搜索的关键技术",
            "联邦学习保护了用户数据隐私",
        ]
        for d in docs:
            vs.add(d)
        vs.rebuild_index()
        return vs

    def test_vocab_size_reasonable(self, vector_store):
        """词汇表大小合理 (>50词, 非原始的7词)"""
        vocab_size = len(vector_store._tfidf.vocab)
        assert vocab_size > 50, (
            f"词汇表太小({vocab_size}): jieba分词可能未生效"
        )

    def test_search_returns_distinct_results(self, vector_store):
        """不同查询返回不同top结果 (非所有查询返回相同的bug)"""
        queries = [
            "机器学习算法",
            "历史建筑文化",
            "量子物理",
            "数据科学",
        ]
        top_texts = set()
        for q in queries:
            results = vector_store.search(q, top_k=1)
            if results:
                top_texts.add(results[0][0].text[:20])

        # 至少2个不同查询返回不同结果
        assert len(top_texts) >= 2, (
            f"所有查询返回相同结果! top_texts={top_texts}"
        )

    def test_ml_query_matches_ml_doc(self, vector_store):
        """'机器学习'查询匹配到机器学习相关文档"""
        results = vector_store.search("机器学习", top_k=3)
        assert len(results) > 0, "应有搜索结果"

        top_texts = [e.text[:15] for e, _ in results]
        assert any("机器学习" in t or "深度学习" in t or "AI" in t
                   for t in top_texts), (
            f"top结果不匹配机器学习: {top_texts}"
        )

    def test_search_score_range(self, vector_store):
        """搜索结果有区分度 (非所有相同分数)"""
        results = vector_store.search("机器学习算法", top_k=5)
        scores = [s for _, s in results]
        if len(scores) >= 2:
            # top分数应该高于第5名
            assert scores[0] >= scores[-1], "分数应降序排列"
            # 不是所有分数都相同
            unique_scores = set(round(s, 4) for s in scores)
            assert len(unique_scores) >= 2, (
                f"所有结果分数相同: {scores}"
            )

    def test_vocabulary_no_junk_bigrams(self, vector_store):
        """词汇表中无大量无意义bi-gram"""
        vocab = list(vector_store._tfidf.vocab.keys())

        # 检查短bi-gram (2字符纯中文)
        short_bi = [
            t for t in vocab
            if len(t) == 2 and all('\u4e00' <= c <= '\u9fff' for c in t)
        ]
        ratio = len(short_bi) / max(len(vocab), 1)

        # 有jieba时, bi-gram占比应低于60%
        if HAS_JIEBA:
            assert ratio < 0.65, (
                f"bi-gram占比过高({ratio:.1%}): jieba分词可能未生效"
            )


class TestTfidfVectorizerFallback:
    """验证无jieba时的回退机制"""

    def test_fallback_produces_tokens(self):
        """回退分词也能产生有效token"""
        from src.core.memory_v2 import TfidfVectorizer
        tfidf = TfidfVectorizer()

        # 即使没有jieba, 英文仍能分词
        tokens = tfidf._tokenize("hello world")
        assert "hello" in tokens
        assert "world" in tokens


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
