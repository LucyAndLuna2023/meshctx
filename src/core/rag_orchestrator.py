"""
meshctx RAG Orchestrator — RAG 编排引擎
=========================================
完整的 RAG 流水线: 检索 → 重排 → 上下文组装 → 引用追踪。

核心能力:
  1. 检索编排 — 多策略检索 + 结果合并
  2. 重排序 — 交叉编码器精排 / 分数融合
  3. 上下文窗口管理 — Token 计数 + 智能截断 + 优先级裁剪
  4. Chunk 策略 — 固定大小 / 语义分割 / 重叠窗口
  5. 引用追踪 — 来源标注 + 引用块映射
  6. 多轮对话 — 上下文合并 + 增量更新

Chunk 策略:
  - fixed:      固定 token 数切分
  - semantic:   按段落/句子边界切分
  - overlap:    固定切分 + 指定重叠比例
  - recursive:  递归字符分割 (优先级: 段落 > 句子 > 词 > 字符)

上下文窗口管理:
  - Token 预算分配: system_prompt + history + retrieved + response
  - 智能截断: 优先保留高相关度 chunk，按分数裁剪低相关 chunk
  - 溢出处理: 摘要压缩 / 分页检索

设计原则:
  - 零外部强制依赖: 纯 Python 实现
  - Token 估算: 使用字符数近似 (1 token ≈ 4 chars English)
  - 可插拔: retriever 和 reranker 通过 Callable 注入

API:
  chunk_document(text, strategy, chunk_size, overlap)
  augment(query, retriever_fn, reranker_fn) → AugmentedContext
  build_prompt(context, system_prompt, history)
  get_rag_orchestrator() → RAGOrchestrator singleton (auto-create)
"""

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.rag_orchestrator")


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class TextChunk:
    """文本块"""
    id: str
    text: str
    source: str = ""                   # 来源文档 ID / URL
    index: int = 0                     # 在原文档中的序号
    start_char: int = 0                # 在原文档中的起始字符位置
    end_char: int = 0                  # 在原文档中的结束字符位置
    token_count: int = 0               # 估计 token 数
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def citation(self, **kw) -> str:
        """生成引用字符串"""
        if self.source:
            return f"[{self.source}:{self.index + 1}]"
        return f"[chunk:{self.id[:8]}]"


@dataclass
class RetrievedChunk:
    """检索到的文本块 (带分数)"""
    chunk: TextChunk
    score: float
    rank: int = 0
    retrieval_source: str = ""  # "keyword" / "vector" / "hybrid"


@dataclass
class AugmentedContext:
    """增强上下文"""
    chunks: List[RetrievedChunk]
    assembled_text: str                # 组装后的上下文字符串
    citations: List[str]               # 引用标注列表
    token_count: int                   # 总 token 数
    token_budget: int                  # 分配的 token 预算
    token_used: int                    # 实际使用的 token 数
    truncated: bool = False            # 是否有截断
    retrieval_latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationTurn:
    """对话轮次"""
    role: str                          # "user" / "assistant" / "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    citations: List[str] = field(default_factory=list)
    token_count: int = 0


# ═══════════════════════════════════════════════════════════
# Token 估算
# ═══════════════════════════════════════════════════════════

class TokenEstimator:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Token 数量估算器

    使用字符数近似 (保守估计):
      - English: ~4 chars/token
      - Code: ~3 chars/token (更多特殊字符)
      - Chinese/Japanese: ~1.5 chars/token

    精确计数需要 tiktoken 库 (可选依赖)。
    """

    # 每 token 平均字符数 (不同语言)
    CHAR_PER_TOKEN = {
        "english": 4.0,
        "code": 3.0,
        "chinese": 1.5,
        "default": 4.0,
    }

    @classmethod
    def estimate(cls, text: str, lang: str = "default", **kw) -> int:
        """估算文本的 token 数"""
        if not text:
            return 0
        ratio = cls.CHAR_PER_TOKEN.get(lang, cls.CHAR_PER_TOKEN["default"])
        return max(1, int(len(text) / ratio))

    @classmethod
    def estimate_batch(cls, texts: List[str], lang: str = "default", **kw) -> List[int]:
        """批量估算 token 数"""
        return [cls.estimate(t, lang) for t in texts]

    @classmethod
    def try_tiktoken(cls, text: str, model: str = "gpt-4", **kw) -> Optional[int]:
        """尝试使用 tiktoken 精确计数"""
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model(model)
            return len(enc.encode(text))
        except ImportError:
            return None
        except Exception:
            return None


# ═══════════════════════════════════════════════════════════
# Chunk 策略
# ═══════════════════════════════════════════════════════════

class TextChunker:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """文本分块器 — 多种分块策略"""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50,
                 strategy: str = "semantic"):
        """
        Args:
            chunk_size: 每块最大 token 数
            chunk_overlap: 块之间重叠 token 数
            strategy: 分块策略 ("fixed" / "semantic" / "overlap" / "recursive")
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.strategy = strategy

    def chunk(self, text: str, source: str = "",
              metadata: Optional[Dict] = None) -> List[TextChunk]:
        """分块主入口"""
        if self.strategy == "fixed":
            return self._chunk_fixed(text, source, metadata)
        elif self.strategy == "overlap":
            return self._chunk_overlap(text, source, metadata)
        elif self.strategy == "semantic":
            return self._chunk_semantic(text, source, metadata)
        elif self.strategy == "recursive":
            return self._chunk_recursive(text, source, metadata)
        else:
            return self._chunk_semantic(text, source, metadata)

    def _chunk_fixed(self, text: str, source: str,
                     metadata: Optional[Dict]) -> List[TextChunk]:
        """固定大小分块 (按字符数)"""
        chunks = []
        # 转换为字符级大小: tokens × chars_per_token
        char_size = self.chunk_size * 4  # ~4 chars/token for English
        char_overlap = self.chunk_overlap * 4

        i = 0
        idx = 0
        while i < len(text):
            end = min(i + char_size, len(text))
            chunk_text = text[i:end]
            chunks.append(TextChunk(
                id=f"{source or 'doc'}_{idx}",
                text=chunk_text,
                source=source,
                index=idx,
                start_char=i,
                end_char=end,
                token_count=TokenEstimator.estimate(chunk_text),
                metadata=metadata or {},
            ))
            idx += 1
            i += char_size - char_overlap

        return chunks

    def _chunk_overlap(self, text: str, source: str,
                       metadata: Optional[Dict]) -> List[TextChunk]:
        """重叠窗口分块"""
        return self._chunk_fixed(text, source, metadata)

    def _chunk_semantic(self, text: str, source: str,
                        metadata: Optional[Dict]) -> List[TextChunk]:
        """语义分块 — 按段落/句子边界，尽量不超过 chunk_size

        优先级: 双换行 (段落) > 单换行 > 句子结束标点 > 强制切分
        """
        # 先按段落分割
        paragraphs = re.split(r"\n\s*\n", text)
        chunks = []
        current = ""
        idx = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # 如果当前累积 + 新段落 < chunk_size，合并
            if TokenEstimator.estimate(current + "\n\n" + para) <= self.chunk_size:
                current = (current + "\n\n" + para).strip()
            else:
                # 保存当前块
                if current:
                    chunks.append(self._make_chunk(
                        current, source, idx,
                        metadata,
                    ))
                    idx += 1

                # 如果单个段落超过 chunk_size，按句子切分
                if TokenEstimator.estimate(para) > self.chunk_size:
                    sub_chunks = self._split_by_sentence(
                        para, source, idx, metadata,
                    )
                    chunks.extend(sub_chunks)
                    idx += len(sub_chunks)
                else:
                    current = para

        # 最后一块
        if current:
            chunks.append(self._make_chunk(current, source, idx, metadata))

        return chunks

    def _split_by_sentence(self, text: str, source: str,
                           start_idx: int,
                           metadata: Optional[Dict]) -> List[TextChunk]:
        """按句子边界切分长段落"""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current = ""
        idx = start_idx

        for sent in sentences:
            if TokenEstimator.estimate(current + " " + sent) <= self.chunk_size:
                current = (current + " " + sent).strip()
            else:
                if current:
                    chunks.append(self._make_chunk(current, source, idx, metadata))
                    idx += 1
                # 单个句子超过限制 → 强制按字符切
                if TokenEstimator.estimate(sent) > self.chunk_size:
                    forced = self._chunk_fixed(sent, source, metadata)
                    for fc in forced:
                        fc.index = idx
                        idx += 1
                    chunks.extend(forced)
                else:
                    current = sent

        if current:
            chunks.append(self._make_chunk(current, source, idx, metadata))

        return chunks

    def _chunk_recursive(self, text: str, source: str,
                         metadata: Optional[Dict]) -> List[TextChunk]:
        """递归字符分割 — LangChain 风格

        分隔符优先级: "\n\n" (段落) → "\n" (行) → ". " (句子) → " " (词) → "" (字符)
        """
        separators = ["\n\n", "\n", ". ", "? ", "! ", " ", ""]
        return self._recursive_split(text, separators, source, metadata)

    def _recursive_split(self, text: str, separators: List[str],
                         source: str, metadata: Optional[Dict],
                         idx: int = 0) -> List[TextChunk]:
        """递归分割"""
        # 基础情况: 文本足够小
        if TokenEstimator.estimate(text) <= self.chunk_size:
            return [self._make_chunk(text, source, idx, metadata)]

        # 尝试当前分隔符
        sep = separators[0] if separators else ""
        if not sep:
            # 最后手段: 字符级切分
            return self._chunk_fixed(text, source, metadata)

        splits = text.split(sep)

        # 如果只有一个部分 (分隔符不存在)，尝试下一个分隔符
        if len(splits) == 1:
            return self._recursive_split(text, separators[1:], source, metadata, idx)

        # 合并短片段，切分长片段
        chunks = []
        current = ""
        for part in splits:
            part_with_sep = part + (sep if sep != "" else "")

            if TokenEstimator.estimate(current + part_with_sep) <= self.chunk_size:
                current += part_with_sep
            else:
                if current:
                    chunks.append(self._make_chunk(current, source, idx + len(chunks), metadata))
                # 递归处理当前部分
                sub = self._recursive_split(
                    part_with_sep, separators[1:], source, metadata,
                    idx + len(chunks),
                )
                chunks.extend(sub)
                current = ""

        if current:
            chunks.append(self._make_chunk(current, source, idx + len(chunks), metadata))

        return chunks

    def _make_chunk(self, text: str, source: str, index: int,
                    metadata: Optional[Dict]) -> TextChunk:
        """创建 TextChunk"""
        return TextChunk(
            id=f"{source or 'doc'}_{index}",
            text=text.strip(),
            source=source,
            index=index,
            start_char=0,
            end_char=len(text),
            token_count=TokenEstimator.estimate(text),
            metadata=metadata or {},
        )


# ═══════════════════════════════════════════════════════════
# 上下文窗口管理器
# ═══════════════════════════════════════════════════════════

class ContextWindowManager:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """上下文窗口管理器

    管理 Token 预算分配:
      - system_prompt: 固定分配
      - history: 对话历史 (可滚动)
      - retrieved: 检索上下文 (动态)
      - response: 预留响应空间

    智能截断策略:
      1. 优先保留高分 chunk
      2. 按分数从低到高裁剪
      3. 必要时摘要压缩历史
    """

    def __init__(self, max_tokens: int = 4096,
                 system_prompt_tokens: int = 200,
                 response_reserve_tokens: int = 1024,
                 max_history_tokens: int = 1500):
        """
        Args:
            max_tokens: 总上下文窗口大小
            system_prompt_tokens: system prompt 保留 token
            response_reserve_tokens: 回复预留 token
            max_history_tokens: 历史消息最大 token
        """
        self.max_tokens = max_tokens
        self.system_prompt_tokens = system_prompt_tokens
        self.response_reserve_tokens = response_reserve_tokens
        self.max_history_tokens = max_history_tokens

    @property
    def retrieval_budget(self, **kw) -> int:
        """检索可用 token 预算"""
        return self.max_tokens - (
            self.system_prompt_tokens +
            self.max_history_tokens +
            self.response_reserve_tokens
        )

    def allocate(self,
                 chunks: List[RetrievedChunk],
                 max_chunks: Optional[int] = None) -> Tuple[List[RetrievedChunk], int]:
        """分配上下文空间给检索结果

        按分数从高到低填充，直到达到 token 预算。

        Args:
            chunks: 检索结果列表 (已排序)
            max_chunks: 最大 chunk 数量

        Returns:
            (selected_chunks, total_tokens_used)
        """
        budget = self.retrieval_budget
        selected = []
        used_tokens = 0

        for chunk in chunks:
            if max_chunks and len(selected) >= max_chunks:
                break

            ct = chunk.chunk.token_count
            if used_tokens + ct > budget:
                break

            selected.append(chunk)
            used_tokens += ct

        return selected, used_tokens

    def trim_chunks(self, chunks: List[RetrievedChunk],
                    max_tokens: int) -> List[RetrievedChunk]:
        """按 token 预算裁剪 chunks (保留高分)"""
        # 按分数排序
        sorted_chunks = sorted(chunks, key=lambda c: c.score, reverse=True)
        selected = []
        used = 0

        for chunk in sorted_chunks:
            ct = chunk.chunk.token_count
            if used + ct > max_tokens:
                # 尝试截断最后一个 chunk 的文本
                remaining = max_tokens - used
                if remaining > 20:  # 至少保留一些有意义的内容
                    truncated = self._truncate_text(chunk.chunk.text, remaining)
                    truncated_chunk = RetrievedChunk(
                        chunk=TextChunk(
                            id=chunk.chunk.id,
                            text=truncated,
                            source=chunk.chunk.source,
                            index=chunk.chunk.index,
                            token_count=TokenEstimator.estimate(truncated),
                            metadata=chunk.chunk.metadata,
                        ),
                        score=chunk.score,
                        rank=chunk.rank,
                        retrieval_source=chunk.retrieval_source,
                    )
                    selected.append(truncated_chunk)
                break
            selected.append(chunk)
            used += ct

        return selected

    def _truncate_text(self, text: str, max_tokens: int, **kw) -> str:
        """截断文本到指定 token 数"""
        max_chars = max_tokens * 4  # 粗略估算
        if len(text) <= max_chars:
            return text
        # 在句子边界截断
        truncated = text[:max_chars]
        last_period = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
        if last_period > max_chars * 0.5:
            return truncated[:last_period + 1]
        return truncated + "..."

    def summarize_history(self, history: List[ConversationTurn],
                          max_tokens: Optional[int] = None) -> str:
        """摘要压缩历史消息"""
        max_t = max_tokens or self.max_history_tokens
        lines = []
        used = 0

        # 从最近的开始，保留更多近期对话
        for turn in reversed(history):
            line = f"{turn.role}: {turn.content}"
            lt = TokenEstimator.estimate(line)
            if used + lt > max_t:
                break
            lines.insert(0, line)
            used += lt

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 引用追踪器
# ═══════════════════════════════════════════════════════════

class CitationTracker:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """引用追踪 — 管理检索块与来源的映射"""

    def __init__(self, **kw):
        self._citations: Dict[str, Dict[str, Any]] = {}  # chunk_id → citation_info
        self._source_docs: Dict[str, str] = {}            # source → title/name

    def register(self, chunk: TextChunk, **kw):
        """注册 chunk 引用"""
        self._citations[chunk.id] = {
            "chunk_id": chunk.id,
            "source": chunk.source,
            "index": chunk.index,
            "text_preview": chunk.text[:100] + "..." if len(chunk.text) > 100 else chunk.text,
            "citation": chunk.citation,
        }

    def register_source(self, source: str, title: str = "", **kw):
        """注册来源文档"""
        self._source_docs[source] = title or source

    def get_formatted_citations(self, chunk_ids: Optional[List[str]] = None, **kw) -> List[str]:
        """获取格式化的引用列表

        Returns:
            ["[source1:chunk0] text preview...", ...]
        """
        ids = chunk_ids or list(self._citations.keys())
        citations = []
        for cid in ids:
            if cid in self._citations:
                cit = self._citations[cid]
                title = self._source_docs.get(cit["source"], cit["source"])
                citations.append(
                    f"[{title}:{cit['index'] + 1}] {cit['text_preview']}"
                )
        return citations

    def get_citation_map(self, **kw) -> Dict[str, str]:
        """获取引用标记 → 文本预览 映射"""
        return {
            cit["citation"]: cit["text_preview"]
            for cit in self._citations.values()
        }


# ═══════════════════════════════════════════════════════════
# RAG Orchestrator 主类
# ═══════════════════════════════════════════════════════════

class RAGOrchestrator:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """RAG 编排引擎

    完整的 RAG 流水线:
      1. 文档分块 (chunk_document)
      2. 检索 (augment)
      3. 重排序
      4. 上下文窗口管理
      5. 上下文组装 (build_prompt)
      6. 引用追踪
      7. 多轮对话合并
    """

    def __init__(self,
                 chunk_size: int = 512,
                 chunk_overlap: int = 50,
                 chunk_strategy: str = "semantic",
                 max_context_tokens: int = 4096,
                 system_prompt_tokens: int = 200,
                 response_reserve_tokens: int = 1024,
                 max_history_turns: int = 10,
                 enable_reranking: bool = True):
        """
        Args:
            chunk_size: 默认分块大小 (tokens)
            chunk_overlap: 默认重叠大小 (tokens)
            chunk_strategy: 分块策略
            max_context_tokens: 最大上下文窗口
            system_prompt_tokens: system prompt token 预算
            response_reserve_tokens: 回复 token 预算
            max_history_turns: 最大历史轮次
            enable_reranking: 是否启用重排序
        """
        self.chunker = TextChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            strategy=chunk_strategy,
        )
        self.window_mgr = ContextWindowManager(
            max_tokens=max_context_tokens,
            system_prompt_tokens=system_prompt_tokens,
            response_reserve_tokens=response_reserve_tokens,
        )
        self.citation_tracker = CitationTracker()
        self.max_history_turns = max_history_turns
        self.enable_reranking = enable_reranking

        self._history: List[ConversationTurn] = []
        self._indexed_chunks: Dict[str, TextChunk] = {}  # chunk_id → chunk
        self._lock = threading.RLock()
        self._stats = {
            "chunks_created": 0,
            "queries_processed": 0,
            "total_tokens_retrieved": 0,
        }

        logger.info(f"RAGOrchestrator initialized: chunk_size={chunk_size}, "
                    f"strategy={chunk_strategy}, max_context={max_context_tokens}")

    # ── 文档处理 ────────────────────────────────────────

    def chunk_document(self, text: str, source: str = "",
                       chunk_size: Optional[int] = None,
                       chunk_overlap: Optional[int] = None,
                       strategy: Optional[str] = None,
                       metadata: Optional[Dict] = None) -> List[TextChunk]:
        """文档分块

        Args:
            text: 文档文本
            source: 来源标识
            chunk_size: 块大小 (覆盖默认)
            chunk_overlap: 重叠大小 (覆盖默认)
            strategy: 分块策略 (覆盖默认)
            metadata: 附加元数据

        Returns:
            TextChunk 列表
        """
        # 临时调整参数
        if chunk_size or chunk_overlap or strategy:
            temp_chunker = TextChunker(
                chunk_size=chunk_size or self.chunker.chunk_size,
                chunk_overlap=chunk_overlap or self.chunker.chunk_overlap,
                strategy=strategy or self.chunker.strategy,
            )
            chunks = temp_chunker.chunk(text, source, metadata)
        else:
            chunks = self.chunker.chunk(text, source, metadata)

        # 注册到索引和引用追踪
        with self._lock:
            for chunk in chunks:
                self._indexed_chunks[chunk.id] = chunk
                self.citation_tracker.register(chunk)
            self._stats["chunks_created"] += len(chunks)

        logger.debug(f"Chunked '{source}' into {len(chunks)} chunks "
                     f"(strategy={strategy or self.chunker.strategy})")
        return chunks

    def chunk_documents(self, documents: List[Dict[str, Any]],
                        text_key: str = "text",
                        source_key: str = "source",
                        **kwargs) -> Dict[str, List[TextChunk]]:
        """批量文档分块

        Returns:
            {source: [TextChunk, ...]}
        """
        result = {}
        for doc in documents:
            source = doc.get(source_key, f"doc_{len(result)}")
            text = doc[text_key]
            result[source] = self.chunk_document(text, source=source, **kwargs)
        return result

    # ── RAG 增强 ────────────────────────────────────────

    def augment(self, query: str,
                retriever_fn: Callable[[str, int], List[RetrievedChunk]],
                k: int = 10,
                reranker_fn: Optional[Callable[[str, List[RetrievedChunk]],
                                                List[RetrievedChunk]]] = None,
                max_chunks: Optional[int] = None,
                max_tokens: Optional[int] = None) -> AugmentedContext:
        """RAG 增强: 检索 → 重排序 → 上下文组装

        Args:
            query: 查询文本
            retriever_fn: 检索函数 (query, k) → [RetrievedChunk, ...]
            k: 检索数量
            reranker_fn: 可选的重排序函数 (query, chunks) → [RetrievedChunk, ...]
            max_chunks: 最大返回 chunk 数
            max_tokens: 最大 token 预算

        Returns:
            AugmentedContext 包含组装后的上下文
        """
        t0 = time.time()

        # 1. 检索
        retrieved = retriever_fn(query, k)

        # 2. 重排序
        if self.enable_reranking and reranker_fn:
            retrieved = reranker_fn(query, retrieved)
        elif self.enable_reranking:
            retrieved = self._default_rerank(query, retrieved)

        # 3. 上下文分配
        budget = max_tokens or self.window_mgr.retrieval_budget
        selected, tokens_used = self.window_mgr.allocate(
            retrieved, max_chunks=max_chunks,
        )

        # 如果超出预算，裁剪
        if tokens_used > budget:
            selected = self.window_mgr.trim_chunks(retrieved, budget)
            tokens_used = sum(c.chunk.token_count for c in selected)

        # 4. 组装文本
        assembled = self._assemble_context(selected)

        # 5. 构建引用列表
        citations = [
            chunk.chunk.citation for chunk in selected
        ]

        latency = (time.time() - t0) * 1000

        with self._lock:
            self._stats["queries_processed"] += 1
            self._stats["total_tokens_retrieved"] += tokens_used

        return AugmentedContext(
            chunks=selected,
            assembled_text=assembled,
            citations=citations,
            token_count=tokens_used,
            token_budget=budget,
            token_used=tokens_used,
            truncated=len(selected) < len(retrieved),
            retrieval_latency_ms=latency,
            metadata={
                "query": query,
                "num_retrieved": len(retrieved),
                "num_selected": len(selected),
            },
        )

    def _default_rerank(self, query: str,
                        chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
        """默认重排序: 按分数排序 + 去重"""
        # 去重
        seen = set()
        unique = []
        for chunk in sorted(chunks, key=lambda c: c.score, reverse=True):
            if chunk.chunk.id not in seen:
                seen.add(chunk.chunk.id)
                unique.append(chunk)

        # 更新排名
        for i, chunk in enumerate(unique):
            chunk.rank = i + 1

        return unique

    def _assemble_context(self, chunks: List[RetrievedChunk], **kw) -> str:
        """组装上下文文本"""
        sections = []
        for i, rc in enumerate(chunks):
            citation = rc.chunk.citation
            sections.append(
                f"{citation}\n{rc.chunk.text}\n"
            )
        return "\n".join(sections)

    # ── Prompt 构建 ─────────────────────────────────────

    def build_prompt(self, context: AugmentedContext,
                     system_prompt: str = "",
                     user_query: Optional[str] = None,
                     include_history: bool = True,
                     include_citations: bool = True) -> str:
        """构建完整的 RAG prompt

        Args:
            context: 增强上下文
            system_prompt: 系统指令
            user_query: 用户查询 (None 则从 context.metadata 中提取)
            include_history: 是否包含对话历史
            include_citations: 是否在上下文中包含引用标记

        Returns:
            完整的 prompt 字符串
        """
        parts = []

        # System prompt
        if system_prompt:
            parts.append(f"System: {system_prompt}\n")

        # 检索上下文
        if include_citations:
            parts.append("Relevant Context (with citations):\n")
            parts.append(context.assembled_text)
            parts.append("")
        else:
            # 无引用的纯上下文
            parts.append("Relevant Context:\n")
            for rc in context.chunks:
                parts.append(rc.chunk.text + "\n")
            parts.append("")

        # 对话历史
        if include_history and self._history:
            history_text = self.window_mgr.summarize_history(self._history)
            if history_text:
                parts.append(f"Conversation History:\n{history_text}\n")

        # 用户查询
        query = user_query or context.metadata.get("query", "")
        if query:
            parts.append(f"User Query: {query}\n")

        if include_citations:
            parts.append(
                "\nInstructions: Answer the query using the provided context. "
                "Cite sources using the [source:index] notation when referencing "
                "specific information from the context."
            )

        return "\n".join(parts)

    def build_messages(self, context: AugmentedContext,
                       system_prompt: str = "",
                       user_query: Optional[str] = None,
                       include_history: bool = True) -> List[Dict[str, str]]:
        """构建 OpenAI-compatible messages 格式

        Returns:
            [{"role": "system", "content": ...}, {"role": "user", "content": ...}, ...]
        """
        messages = []

        # System message
        sys_content = system_prompt
        if context.assembled_text:
            sys_content += (
                f"\n\nRelevant context for answering the user's question:\n"
                f"{context.assembled_text}"
            )
        messages.append({"role": "system", "content": sys_content})

        # History
        if include_history:
            for turn in self._history[-self.max_history_turns:]:
                messages.append({"role": turn.role, "content": turn.content})

        # User query
        query = user_query or context.metadata.get("query", "")
        if query:
            messages.append({"role": "user", "content": query})

        return messages

    # ── 多轮对话 ────────────────────────────────────────

    def add_turn(self, role: str, content: str,
                 citations: Optional[List[str]] = None):
        """添加对话轮次"""
        turn = ConversationTurn(
            role=role,
            content=content,
            citations=citations or [],
            token_count=TokenEstimator.estimate(content),
        )
        with self._lock:
            self._history.append(turn)

        # 限制历史长度
        if len(self._history) > self.max_history_turns * 2:
            with self._lock:
                self._history = self._history[-self.max_history_turns * 2:]

    def get_history(self, n: Optional[int] = None, **kw) -> List[ConversationTurn]:
        """获取历史"""
        if n:
            return self._history[-n:]
        return list(self._history)

    def clear_history(self, **kw):
        """清空对话历史"""
        with self._lock:
            self._history.clear()

    def merge_context(self, previous_context: AugmentedContext,
                      new_context: AugmentedContext,
                      deduplicate: bool = True) -> AugmentedContext:
        """合并多轮上下文

        将前一轮的上下文与新检索的上下文合并。

        Args:
            previous_context: 前一轮的增强上下文
            new_context: 新检索的增强上下文
            deduplicate: 是否去重

        Returns:
            合并后的 AugmentedContext
        """
        all_chunks = list(new_context.chunks)

        if deduplicate:
            seen_ids = {c.chunk.id for c in new_context.chunks}
            for rc in previous_context.chunks:
                if rc.chunk.id not in seen_ids:
                    seen_ids.add(rc.chunk.id)
                    all_chunks.append(rc)

        # 重新排序 (按分数)
        all_chunks.sort(key=lambda c: c.score, reverse=True)

        # 重新分配
        selected, tokens_used = self.window_mgr.allocate(all_chunks)

        # 组装
        assembled = self._assemble_context(selected)
        citations = [c.chunk.citation for c in selected]

        return AugmentedContext(
            chunks=selected,
            assembled_text=assembled,
            citations=citations,
            token_count=tokens_used,
            token_budget=self.window_mgr.retrieval_budget,
            token_used=tokens_used,
            truncated=len(selected) < len(all_chunks),
            metadata={
                **new_context.metadata,
                "merged_from_previous": True,
                "num_previous_chunks": len(previous_context.chunks),
                "num_new_chunks": len(new_context.chunks),
            },
        )

    # ── 工具方法 ────────────────────────────────────────

    def get_chunk(self, chunk_id: str, **kw) -> Optional[TextChunk]:
        """获取已索引的 chunk"""
        return self._indexed_chunks.get(chunk_id)

    def get_chunks_by_source(self, source: str, **kw) -> List[TextChunk]:
        """按来源获取所有 chunk"""
        return [
            c for c in self._indexed_chunks.values()
            if c.source == source
        ]

    def stats(self, **kw) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                **self._stats,
                "indexed_chunks": len(self._indexed_chunks),
                "history_turns": len(self._history),
                "chunk_strategy": self.chunker.strategy,
                "chunk_size": self.chunker.chunk_size,
                "max_context_tokens": self.window_mgr.max_tokens,
                "retrieval_budget": self.window_mgr.retrieval_budget,
                "reranking_enabled": self.enable_reranking,
            }

    def reset(self, **kw):
        """重置编排器状态"""
        with self._lock:
            self._history.clear()
            self._indexed_chunks.clear()
            self.citation_tracker = CitationTracker()
            self._stats = {
                "chunks_created": 0,
                "queries_processed": 0,
                "total_tokens_retrieved": 0,
            }
        logger.info("RAGOrchestrator reset")


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_orchestrator: Optional[RAGOrchestrator] = None
_orchestrator_lock = threading.Lock()


def get_rag_orchestrator(
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    chunk_strategy: str = "semantic",
    max_context_tokens: int = 4096,
    **kwargs,
) -> RAGOrchestrator:
    """获取 RAGOrchestrator 全局单例 (auto-create)

    Args:
        chunk_size: 分块大小
        chunk_overlap: 重叠大小
        chunk_strategy: 分块策略
        max_context_tokens: 最大上下文窗口
        **kwargs: 传递给 RAGOrchestrator() 的其他参数

    Returns:
        RAGOrchestrator 实例
    """
    global _orchestrator
    if _orchestrator is None:
        with _orchestrator_lock:
            if _orchestrator is None:
                _orchestrator = RAGOrchestrator(
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    chunk_strategy=chunk_strategy,
                    max_context_tokens=max_context_tokens,
                    **kwargs,
                )
    return _orchestrator


def reset_rag_orchestrator():
    """重置全局实例 (用于测试)"""
    global _orchestrator
    with _orchestrator_lock:
        if _orchestrator:
            _orchestrator.reset()
        _orchestrator = None
