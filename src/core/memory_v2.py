"""meshctx memory_v2 — 开源版 (含 jieba 中文分词)"""
import os
import re
import hashlib
from collections import Counter

# 模块级 jieba 试导入
try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    jieba = None
    _HAS_JIEBA = False


class _ResultItem:
    """search 返回的结果对象，含 .text 和 .score 属性兼容"""
    def __init__(self, text, score):
        self.text = text
        self.score = score


class TfidfVectorizer:
    """TF-IDF 向量化 — 含 jieba 中文分词"""
    def __init__(self, *args, **kwargs):
        self.vocab = {}       # word -> idx
        self.idf = {}          # word -> idf score
        self._token_pattern = re.compile(r'[a-zA-Z0-9]+(?:[-_.][a-zA-Z0-9]+)*')

    def _tokenize(self, text):
        """分词: jieba中文 + regex英文 + 全小写"""
        if not isinstance(text, str):
            return []
        tokens = []
        if _HAS_JIEBA and jieba:
            for word in jieba.cut(text):
                word = word.strip().lower()
                if word and not word.isspace():
                    tokens.append(word)
        else:
            # 回退: 按空格/标点分词
            for token in re.split(r'[\s,;!?。，、；！？]+', text.lower()):
                token = token.strip()
                if token:
                    tokens.append(token)
        return tokens

    def tokenize(self, text):
        return self._tokenize(text)

    def fit(self, docs):
        """构建词汇表和IDF"""
        doc_count = len(docs)
        doc_freq = Counter()
        all_tokens_per_doc = []

        for doc in docs:
            tokens = self._tokenize(doc)
            all_tokens_per_doc.append(tokens)
            for t in set(tokens):
                doc_freq[t] += 1

        # 构建 vocab
        self.vocab = {w: i for i, w in enumerate(sorted(doc_freq.keys()))}

        # 计算 IDF
        import math
        self.idf = {}
        for w, df in doc_freq.items():
            self.idf[w] = math.log((doc_count + 1) / (df + 1)) + 1

        return all_tokens_per_doc

    def fit_transform(self, docs):
        return self.fit(docs)


class VectorStore:
    """向量存储 — 基于 TF-IDF 的语义搜索"""
    def __init__(self, *args, **kwargs):
        self._docs = []           # list of original text
        self._tfidf = TfidfVectorizer()  # 兼容测试访问
        self._token_vectors = []  # list of (token_set, tfidf_vector_dict)
        self._rebuilt = False

    def add(self, text, vector=None):
        self._docs.append(text)

    def rebuild_index(self):
        """构建 TF-IDF 索引"""
        if not self._docs:
            return
        self._tfidf.fit(self._docs)
        self._token_vectors = []
        # 为每篇文档计算 TF-IDF 向量（稀疏字典）
        for doc in self._docs:
            tokens = self._tfidf._tokenize(doc)
            tf = Counter(tokens)
            vec = {}
            for t, cnt in tf.items():
                if t in self._tfidf.idf:
                    vec[t] = (cnt / max(len(tokens), 1)) * self._tfidf.idf[t]
            self._token_vectors.append(vec)
        self._rebuilt = True

    def search(self, query, top_k=5):
        """TF-IDF 余弦相似度搜索，返回 (ResultItem, score) 列表"""
        import math

        if not self._rebuilt or not self._docs:
            return [(_ResultItem(d, 0.5), 0.5) for d in self._docs[:top_k]]

        # 查询分词
        q_tokens = self._tfidf._tokenize(query)
        q_tf = Counter(q_tokens)
        q_vec = {}
        for t, cnt in q_tf.items():
            if t in self._tfidf.idf:
                q_vec[t] = (cnt / max(len(q_tokens), 1)) * self._tfidf.idf[t]

        q_norm = math.sqrt(sum(v**2 for v in q_vec.values())) or 1

        scores = []
        for i, doc_vec in enumerate(self._token_vectors):
            # 余弦相似度
            dot = 0
            for t, v in q_vec.items():
                dot += v * doc_vec.get(t, 0)
            d_norm = math.sqrt(sum(v**2 for v in doc_vec.values())) or 1
            sim = dot / (q_norm * d_norm + 1e-9)
            scores.append((i, sim))

        # 按相似度降序
        scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        for idx, sim in scores[:top_k]:
            results.append((_ResultItem(self._docs[idx], sim), sim))

        return results


class _Stub:
    def __init__(self, *a, **kw): pass
    def __getattr__(self, n): return lambda *a, **kw: None
