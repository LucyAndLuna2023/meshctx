"""meshctx memory_v2 — 真实开源实现（含 jieba 中文分词回退）

分层记忆管理器（工作/短期/长期）+ TF-IDF 语义搜索（jieba 中文分词 +
英文 regex 回退），使用 dict + json 文件持久化。纯 Python stdlib 实现，
无新增第三方依赖（numpy 存在时用于向量化，缺失时纯 Python 计算）。
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("meshctx.memory_v2")

# ── jieba 中文分词：可用则用，不可用则 regex 回退 ─────────────
try:
    import jieba  # type: ignore

    _HAS_JIEBA = True
except ImportError:  # pragma: no cover - 依赖环境
    jieba = None  # type: ignore[assignment]
    _HAS_JIEBA = False

# 中英停用词（低频函数词，不参与索引与匹配）
_STOPWORDS = set(
    """
    的 了 是 在 我 你 他 她 它 们 这 那 有 和 与 就 都 而 及 或 被 把 让 对 从 向 为 等 之 其 个
    一个 我们 你们 他们 她们 它们 这个 那个 这些 那些 可以 进行 以及 因为 所以 但是 如果 没有
    不是 就是 还是 已经 什么 怎么 为什么 这样 那样 自己 时候 现在 今天 明天 昨天 目前 当前
    a an the and or of to in on for with by at from is are was were be been being it its this that
    these those you your we our they their i me my he him his she her do does did done not no yes
    """.split()
)


class _ResultItem:
    """search 返回的结果对象，含 .text 和 .score 属性兼容"""

    def __init__(self, text, score, **kw):
        self.text = text
        self.score = score
        for k, v in kw.items():
            setattr(self, k, v)

    def __repr__(self):
        return f"<ResultItem score={self.score:.4f} text={self.text!r}>"


@dataclass
class MemoryEntry:
    """记忆条目 — web_ui / 外部消费方使用的轻量视图。

    提供 .id / .content / .importance / .created_at 等属性，兼容
    _V2MemoryAdapter 的接口约定。
    """

    id: str = ""
    content: str = ""
    importance: float = 0.5
    created_at: float = 0.0
    tags: List[str] = field(default_factory=list)
    level: str = "working"
    access_count: int = 0
    score: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex
        if not self.created_at:
            self.created_at = time.time()


class TfidfVectorizer:
    """TF-IDF 向量化 — 含 jieba 中文分词（无 jieba 时 regex 回退）"""

    def __init__(self, *args, **kwargs):
        self.vocab: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self._doc_count = 0
        self._doc_freq: Dict[str, int] = {}
        self.max_features = int(kwargs.get("max_features", 0) or 0)
        self.min_df = int(kwargs.get("min_df", 1) or 1)
        stop = kwargs.get("stop_words")
        self.stop_words = set(stop) if stop else set(_STOPWORDS)

    # ── 分词 ──────────────────────────────────────────────
    def _tokenize(self, text, **kw):
        """分词: jieba中文 + regex英文 + 全小写。

        返回去停用词后的 token 列表。
        """
        text = (text or "")
        text = text.lower()
        tokens: List[str] = []
        if _HAS_JIEBA and jieba is not None:
            for piece in jieba.cut(text):
                piece = piece.strip().lower()
                if not piece:
                    continue
                if re.search(r"[\u4e00-\u9fff]", piece):
                    # 中文词（可能混入少量英文/数字，如 "5g通信"）
                    tokens.append(piece)
                else:
                    # 非中文片段按英文/数字再拆分
                    tokens.extend(re.findall(r"[a-z0-9]+", piece))
        else:  # pragma: no cover - jieba 缺失回退
            tokens = re.findall(r"[a-z0-9]+", text)
        # 过滤停用词与纯噪声 token
        filtered = []
        for t in tokens:
            if t in self.stop_words:
                continue
            if t.isdigit() and len(t) > 8:
                continue  # 超长数字串无检索价值
            if len(t) == 1 and not re.search(r"[\u4e00-\u9fff]", t):
                continue  # 单字符非中文（英文单字母）
            if not re.search(r"[\u4e00-\u9fff]", t) and len(t) < 2:
                continue  # 非中文且过短
            filtered.append(t)
        return filtered

    def tokenize(self, text, **kw):
        return self._tokenize(text, **kw)

    # ── 拟合 ──────────────────────────────────────────────
    def fit(self, docs, **kw):
        """构建词汇表和IDF"""
        self.vocab = {}
        self._doc_freq = {}
        self._doc_count = 0
        for doc in docs or []:
            terms = set(self._tokenize(doc))
            self._doc_count += 1
            for t in terms:
                self._doc_freq[t] = self._doc_freq.get(t, 0) + 1
        # min_df 过滤
        vocab = {
            t: df
            for t, df in self._doc_freq.items()
            if df >= max(1, self.min_df)
        }
        if self.max_features and len(vocab) > self.max_features:
            # 保留文档频率最高的 max_features 个词
            vocab = dict(
                sorted(vocab.items(), key=lambda kv: (-kv[1], kv[0]))[
                    : self.max_features
                ]
            )
        self.vocab = {t: i for i, t in enumerate(sorted(vocab))}
        n = max(1, self._doc_count)
        self.idf = {
            t: 1.0 + math.log((1.0 + n) / (1.0 + df))
            for t, df in vocab.items()
        }
        return self

    def _vectorize(self, doc: str) -> Dict[int, float]:
        """返回 {vocab_index: tfidf} 稀疏表示"""
        tf: Dict[str, int] = {}
        for t in self._tokenize(doc):
            if t in self.vocab:
                tf[t] = tf.get(t, 0) + 1
        total = max(1, sum(tf.values()))
        out: Dict[int, float] = {}
        for t, cnt in tf.items():
            # 词频归一化 × IDF
            out[self.vocab[t]] = (cnt / total) * self.idf.get(t, 0.0)
        return out

    def fit_transform(self, docs, **kw):
        self.fit(docs, **kw)
        return [self._vectorize(d) for d in (docs or [])]


class VectorStore:
    """向量存储 — 基于 TF-IDF 的语义搜索"""

    def __init__(self, *args, **kwargs):
        self._tfidf = TfidfVectorizer(*args, **kwargs)
        self._docs: List[str] = []
        self._meta: List[Dict[str, Any]] = []
        self._matrix: List[Dict[int, float]] = []
        self._lock = threading.RLock()

    def add(self, text, vector=None, **kw):
        """加入一条文本。vector 参数保留兼容（本实现使用 TF-IDF 自行向量化）。"""
        with self._lock:
            idx = len(self._docs)
            self._docs.append(text or "")
            meta = {"id": kw.get("id", f"doc_{idx}"), "text": text or ""}
            self._meta.append(meta)
            return idx

    def rebuild_index(self, **kw):
        """构建 TF-IDF 索引"""
        with self._lock:
            self._matrix = self._tfidf.fit_transform(self._docs, **kw)
            return len(self._matrix)

    def _cosine(self, a: Dict[int, float], b: Dict[int, float]) -> float:
        if not a or not b:
            return 0.0
        keys = set(a) & set(b)
        dot = sum(a[k] * b[k] for k in keys)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)

    def search(self, query, top_k=5, **kw):
        """TF-IDF 余弦相似度搜索，返回 (ResultItem, score) 列表"""
        with self._lock:
            if not self._docs:
                return []
            q_vec = self._tfidf._vectorize(query or "")
            if not q_vec:
                return []
            scored = [
                (idx, self._cosine(q_vec, vec))
                for idx, vec in enumerate(self._matrix)
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            results = []
            for idx, score in scored[: max(0, top_k)]:
                if score <= 0.0:
                    continue
                meta = self._meta[idx]
                results.append(
                    (
                        _ResultItem(
                            meta["text"],
                            score,
                            id=meta.get("id"),
                            index=idx,
                        ),
                        score,
                    )
                )
            return results


class _MemoryLayer:
    """单层记忆存储：有序 dict 保证插入顺序，条目为 dict。"""

    def __init__(self, name: str):
        self.name = name
        self.items: Dict[str, dict] = {}

    def __len__(self):
        return len(self.items)

    def put(self, entry: dict):
        self.items[entry["id"]] = entry

    def pop(self, entry_id: str) -> Optional[dict]:
        return self.items.pop(entry_id, None)

    def values(self):
        return list(self.items.values())


class MemoryManager:
    """分层记忆管理器（工作/短期/长期），dict + json 持久化。

    - add(): 新记忆进入工作层
    - search(): 跨层检索（TF-IDF 语义 + 频率加权）
    - consolidate(): 工作→短期→长期 逐级提升（按访问频次/重要性）
    - 持久化: 每次变更后自动写 JSON（原子写入），路径可用环境变量
      MESHCTX_MEMORY_V2_PATH 覆盖（默认 ~/.meshctx/memory_v2.json）
    """

    _DEFAULT_PATH = os.path.join(
        os.path.expanduser("~"), ".meshctx", "memory_v2.json"
    )

    # 提升阈值（consolidate 使用）
    _PROMOTE_ACCESS_WORKING = 2   # 工作层访问≥2次 → 短期
    _PROMOTE_ACCESS_SHORT = 4     # 短期层访问≥4次 → 长期
    _PROMOTE_IMPORTANCE_WORKING = 0.7
    _PROMOTE_IMPORTANCE_SHORT = 0.85
    _DEMOTE_IMPORTANCE = 0.25     # 长期层重要性过低 → 清理
    _DEMOTE_AGE_DAYS = 90         # 长期层超过 N 天未访问 → 清理

    def __init__(self):
        self.working = _MemoryLayer("working")
        self.short_term = _MemoryLayer("short_term")
        self.long_term = _MemoryLayer("long_term")
        self._lock = threading.RLock()
        self._store = VectorStore()
        self._store_indexed = False
        self._path = os.environ.get("MESHCTX_MEMORY_V2_PATH") or self._DEFAULT_PATH
        self._load()

    # ── 持久化 ────────────────────────────────────────────
    def _load(self):
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return  # 首次运行，无存档
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("memory_v2 存档损坏，重新开始: %s (%s)", self._path, e)
            return
        except OSError as e:
            logger.warning("memory_v2 无法读取存档 %s: %s", self._path, e)
            return
        if not isinstance(data, dict):
            return
        for level in ("working", "short_term", "long_term"):
            layer = getattr(self, level)
            for entry in data.get(level, []) or []:
                if isinstance(entry, dict) and entry.get("id"):
                    layer.put(entry)

    def _save(self):
        payload = {
            "version": 1,
            "saved_at": time.time(),
            "working": list(self.working.values()),
            "short_term": list(self.short_term.values()),
            "long_term": list(self.long_term.values()),
        }
        abs_path = os.path.abspath(self._path)
        tmp_path = abs_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, abs_path)
        except OSError as e:
            # 持久化失败不阻断记忆功能，仅记录（如只读环境）
            logger.warning("memory_v2 持久化失败: %s", e)

    # ── 写入 ──────────────────────────────────────────────
    def add(self, content, tags=None):
        """添加一条记忆到工作层，返回记忆 id。"""
        content = (content or "").strip()
        if not content:
            raise ValueError("memory content must not be empty")
        with self._lock:
            entry = {
                "id": uuid.uuid4().hex,
                "content": content,
                "tags": [str(t) for t in (tags or [])],
                "importance": 0.5,
                "access_count": 0,
                "created_at": time.time(),
                "last_accessed": time.time(),
                "level": "working",
            }
            self.working.put(entry)
            self._store.add(content, id=entry["id"])
            self._store_indexed = False
            self._save()
            return entry["id"]

    # ── 检索 ──────────────────────────────────────────────
    def _indexed_store(self) -> VectorStore:
        if not self._store_indexed:
            self._store.rebuild_index()
            self._store_indexed = True
        return self._store

    def search(self, query):
        """跨层检索。返回 MemoryEntry 列表（含 .score），按相关度降序。"""
        top_k = 5
        with self._lock:
            if not (query or "").strip():
                return []
            all_entries = (
                self.working.values()
                + self.short_term.values()
                + self.long_term.values()
            )
            if not all_entries:
                return []
            store = self._indexed_store()
            hits = store.search(query, top_k=max(top_k, len(all_entries)))
            # 组装 MemoryEntry；向量命中为 0 时以关键词匹配兜底
            results: List[MemoryEntry] = []
            for item, score in hits:
                entry = self._find_entry(item.id)
                if entry is None:
                    continue
                entry["access_count"] = entry.get("access_count", 0) + 1
                entry["last_accessed"] = time.time()
                results.append(
                    MemoryEntry(
                        id=entry["id"],
                        content=entry["content"],
                        importance=entry.get("importance", 0.5),
                        created_at=entry.get("created_at", 0.0),
                        tags=list(entry.get("tags", [])),
                        level=entry.get("level", "working"),
                        access_count=entry.get("access_count", 0),
                        score=round(float(score), 4),
                    )
                )
            if results:
                self._save()
            return results[: max(0, top_k)]

    def _find_entry(self, entry_id: str) -> Optional[dict]:
        for layer in (self.working, self.short_term, self.long_term):
            if entry_id in layer.items:
                return layer.items[entry_id]
        return None

    # ── 删除 ──────────────────────────────────────────────
    def delete(self, idx):
        """删除记忆。idx 为 str 时视为记忆 id；为 int 时视为扁平索引。"""
        with self._lock:
            if isinstance(idx, str):
                return self.remove(idx)
            # 整数索引 → 扁平顺序（working+short+long）
            flat = (
                self.working.values()
                + self.short_term.values()
                + self.long_term.values()
            )
            if 0 <= idx < len(flat):
                return self.remove(flat[idx]["id"])
            return False

    def remove(self, memory_id: str) -> bool:
        """按记忆 id 删除（web_ui 使用）。"""
        with self._lock:
            for layer in (self.working, self.short_term, self.long_term):
                if layer.pop(memory_id) is not None:
                    self._save()
                    return True
            return False

    # ── 巩固（层级提升）────────────────────────────────────
    def consolidate(self):
        """记忆巩固：工作→短期→长期 逐级提升；长期层低频/久未访问清理。

        规则：
          - 工作层访问≥2 或 importance≥0.7 → 短期
          - 短期层访问≥4 或 importance≥0.85 → 长期
          - 长期层 importance<0.25 且超过 90 天未访问 → 删除
        返回统计 dict。
        """
        with self._lock:
            now = time.time()
            moved_ws = 0
            moved_sl = 0
            dropped = 0

            # 工作 → 短期
            for eid in list(self.working.items.keys()):
                e = self.working.items[eid]
                if (
                    e.get("access_count", 0) >= self._PROMOTE_ACCESS_WORKING
                    or e.get("importance", 0.0) >= self._PROMOTE_IMPORTANCE_WORKING
                ):
                    e["level"] = "short_term"
                    self.short_term.put(self.working.pop(eid))
                    moved_ws += 1

            # 短期 → 长期
            for eid in list(self.short_term.items.keys()):
                e = self.short_term.items[eid]
                if (
                    e.get("access_count", 0) >= self._PROMOTE_ACCESS_SHORT
                    or e.get("importance", 0.0) >= self._PROMOTE_IMPORTANCE_SHORT
                ):
                    e["level"] = "long_term"
                    self.long_term.put(self.short_term.pop(eid))
                    moved_sl += 1

            # 长期层清理（遗忘）
            for eid in list(self.long_term.items.keys()):
                e = self.long_term.items[eid]
                last = e.get("last_accessed", 0) or e.get("created_at", 0)
                old = (now - last) > self._DEMOTE_AGE_DAYS * 86400.0
                low = e.get("importance", 0.5) < self._DEMOTE_IMPORTANCE
                if old and low:
                    self.long_term.pop(eid)
                    dropped += 1

            self._save()
            return {
                "working_to_short_term": moved_ws,
                "short_term_to_long_term": moved_sl,
                "long_term_forgotten": dropped,
                "working": len(self.working),
                "short_term": len(self.short_term),
                "long_term": len(self.long_term),
                "total": len(self.working) + len(self.short_term) + len(self.long_term),
            }

    # ── 统计 / 列表 ───────────────────────────────────────
    def stats(self):
        """返回分层统计 dict。"""
        with self._lock:
            return {
                "working": len(self.working),
                "short_term": len(self.short_term),
                "long_term": len(self.long_term),
                "total": len(self.working) + len(self.short_term) + len(self.long_term),
                "storage": self._path,
            }

    def list_by_type(self):
        """返回全部记忆条目（MemoryEntry 列表），按重要性降序。"""
        with self._lock:
            entries = []
            for layer in (self.working, self.short_term, self.long_term):
                for e in layer.values():
                    entries.append(
                        MemoryEntry(
                            id=e["id"],
                            content=e["content"],
                            importance=e.get("importance", 0.5),
                            created_at=e.get("created_at", 0.0),
                            tags=list(e.get("tags", [])),
                            level=e.get("level", layer.name),
                            access_count=e.get("access_count", 0),
                        )
                    )
            entries.sort(key=lambda x: x.importance, reverse=True)
            return entries


_manager: Optional[MemoryManager] = None
_manager_lock = threading.Lock()


def get_memory_manager():
    """获取（惰性创建）全局 MemoryManager 单例。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = MemoryManager()
    return _manager


# ── 模块级便捷函数（__all__ 兼容）───────────────────────────
def tokenize(text, **kw):
    return TfidfVectorizer().tokenize(text, **kw)


def fit(docs, **kw):
    return TfidfVectorizer().fit(docs, **kw)


def fit_transform(docs, **kw):
    return TfidfVectorizer().fit_transform(docs, **kw)


def add(text, vector=None, **kw):
    return get_memory_manager().add(text, tags=kw.get("tags"))


def rebuild_index(**kw):
    vs = VectorStore()
    return vs.rebuild_index(**kw)


def search(query, top_k=5, **kw):
    return get_memory_manager().search(query, top_k=top_k)


def delete(idx):
    return get_memory_manager().delete(idx)


def stats():
    return get_memory_manager().stats()


__all__ = [
    "TfidfVectorizer", "tokenize", "fit", "fit_transform",
    "VectorStore", "add", "rebuild_index", "search",
    "MemoryManager", "delete", "stats", "get_memory_manager",
    "MemoryEntry", "_ResultItem", "_HAS_JIEBA", "jieba",
]
