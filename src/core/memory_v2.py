"""meshctx memory_v2 — 开源版 (stub)"""
import os

# 模块级 jieba 试导入
try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    jieba = None
    _HAS_JIEBA = False


class VectorStore:
    """向量存储 — stub"""
    def __init__(self, *args, **kwargs):
        self.vectors = {}
    def add(self, text, vector=None):
        self.vectors[text] = vector or [0.0] * 384
    def search(self, query, top_k=5):
        return [(k, 0.85) for k in list(self.vectors.keys())[:top_k]]
    def rebuild_index(self):
        pass


class TfidfVectorizer:
    """TF-IDF 向量化 — stub (含 jieba 中文分词)"""
    def __init__(self, *args, **kwargs):
        self.vocabulary_ = {}
    def fit_transform(self, docs):
        return [[0.0]]
    def tokenize(self, text):
        tokens = []
        if _HAS_JIEBA:
            for word in jieba.cut(text):
                word = word.strip()
                if word:
                    tokens.append(word)
        else:
            tokens = text.split()
        return tokens
    _tokenize = tokenize  # 别名兼容


class _Stub:
    def __init__(self, *a, **kw): pass
    def __getattr__(self, n): return lambda *a,**kw: None
