"""
meshctx — Knowledge Base Tool (对标 扣子 Coze / CoPaw memory_search)

知识库检索与向量搜索。支持：
- 文本分块 + 嵌入生成 + 向量搜索
- 本地 JSON 知识条目管理
- 语义搜索（需 sentence-transformers / openai）
- 关键词搜索（无依赖回退）

Tool name: knowledge_base
"""

import json
import os
import re
import hashlib
from typing import Any


# ── Storage paths ──

KB_DIR = os.path.expanduser("~/.meshctx/knowledge")
os.makedirs(KB_DIR, exist_ok=True)
KB_INDEX = os.path.join(KB_DIR, "index.json")


# ── Index helpers ──

def _load_index() -> dict:
    """Load the knowledge index from disk."""
    if os.path.exists(KB_INDEX):
        try:
            with open(KB_INDEX, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"entries": {}}
    return {"entries": {}}


def _save_index(idx: dict) -> None:
    """Save the knowledge index atomically."""
    tmp = KB_INDEX + ".tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    os.replace(tmp, KB_INDEX)


def _doc_id(title: str, content: str) -> str:
    """Generate a deterministic document ID."""
    return hashlib.sha256(f"{title}::{content}".encode()).hexdigest()[:16]


# ── Keyword search (fallback, no deps) ──

def _keyword_search(query: str, entries: dict, limit: int = 10) -> list[dict]:
    """Simple TF-ish keyword search over indexed entries."""
    terms = [t.lower() for t in re.split(r'\s+', query) if len(t) > 1]
    if not terms:
        return list(entries.values())[:limit]

    scored = []
    for eid, entry in entries.items():
        text = (entry.get('title', '') + ' ' + entry.get('content', '') + ' ' +
                ' '.join(entry.get('tags', []))).lower()
        score = sum(1 for t in terms if t in text)
        # Bonus for exact phrase match
        if query.lower() in text:
            score += len(terms)
        if score > 0:
            entry['score'] = score
            scored.append(entry)

    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:limit]


# ── Semantic search (optional deps) ──

def _has_embeddings() -> bool:
    """Check if sentence-transformers or openai embeddings are available."""
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import openai  # noqa: F401
        if os.environ.get("OPENAI_API_KEY"):
            return True
    except ImportError:
        pass
    return False


def _encode_query(query: str) -> list[float] | None:
    """Encode a query string into a vector."""
    # Try sentence-transformers first
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        vec = model.encode(query, convert_to_numpy=True)
        return vec.tolist()
    except Exception:
        pass
    # Try OpenAI embeddings
    try:
        import openai
        resp = openai.embeddings.create(
            model="text-embedding-3-small",
            input=query,
            api_key=os.environ.get("OPENAI_API_KEY"),
        )
        return resp.data[0].embedding
    except Exception:
        pass
    return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x ** 2 for x in a) ** 0.5
    norm_b = sum(y ** 2 for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _semantic_search(query: str, entries: dict, limit: int = 10) -> list[dict]:
    """Vector-based semantic search."""
    query_vec = _encode_query(query)
    if query_vec is None:
        return _keyword_search(query, entries, limit)

    scored = []
    for eid, entry in entries.items():
        emb = entry.get('embedding')
        if emb:
            score = _cosine_similarity(query_vec, emb)
            entry['score'] = round(score, 4)
            scored.append(entry)

    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:limit]


# ── Public API ──

def kb_add(title: str, content: str, tags: list[str] | None = None,
           source: str = "", embed: bool = False) -> dict:
    """Add a document to the knowledge base.

    Args:
        title: Document title.
        content: Full document content (will be chunked if > 2000 chars).
        tags: Optional tags for filtering.
        source: Source URL or file path reference.
        embed: Whether to generate embeddings for semantic search.

    Returns:
        {"ok": True, "doc_id": "...", "chunks": N}
    """
    idx = _load_index()
    doc_id = _doc_id(title, content)
    tags = tags or []

    # Chunking for long content
    chunk_size = 2000
    chunks = []
    content_clean = content.strip()
    for i in range(0, len(content_clean), chunk_size):
        chunk = content_clean[i:i + chunk_size]
        chunk_doc_id = doc_id if i == 0 else f"{doc_id}_c{i // chunk_size}"
        entry = {
            "doc_id": chunk_doc_id,
            "group_id": doc_id,
            "title": title,
            "content": chunk,
            "tags": tags,
            "source": source,
            "chunk_index": i // chunk_size,
        }
        if embed and _has_embeddings():
            vec = _encode_query(chunk)
            if vec:
                entry['embedding'] = vec
        idx["entries"][chunk_doc_id] = entry
        chunks.append(entry)

    _save_index(idx)
    return {"ok": True, "doc_id": doc_id, "chunks": len(chunks)}


def kb_search(query: str, limit: int = 10, semantic: bool = False,
              tags: list[str] | None = None) -> dict:
    """Search the knowledge base.

    Args:
        query: Search query.
        limit: Max results.
        semantic: Use semantic (vector) search if embeddings available.
        tags: Filter by tags.

    Returns:
        {"ok": True, "query": ..., "count": N, "results": [{...}]}
    """
    idx = _load_index()
    entries = idx.get("entries", {})

    # Tag filter
    if tags:
        entries = {
            k: v for k, v in entries.items()
            if any(t in v.get('tags', []) for t in tags)
        }

    if semantic and _has_embeddings():
        results = _semantic_search(query, entries, limit)
    else:
        results = _keyword_search(query, entries, limit)

    # Remove embeddings from results for cleaner output
    clean = []
    for r in results:
        c = {k: v for k, v in r.items() if k != 'embedding'}
        clean.append(c)

    return {
        "ok": True,
        "query": query,
        "search_mode": "semantic" if (semantic and _has_embeddings()) else "keyword",
        "count": len(clean),
        "results": clean,
    }


def kb_list(tags: list[str] | None = None, limit: int = 50) -> dict:
    """List all documents in the knowledge base.

    Returns:
        {"ok": True, "count": N, "documents": [...]}
    """
    idx = _load_index()
    entries = idx.get("entries", {})

    # Deduplicate by group_id
    groups = {}
    for eid, entry in entries.items():
        gid = entry.get('group_id', eid)
        if gid not in groups or entry.get('chunk_index', 0) == 0:
            groups[gid] = {
                "doc_id": gid,
                "title": entry['title'],
                "tags": entry.get('tags', []),
                "source": entry.get('source', ''),
                "chunk_count": 0,
            }
        groups[gid]['chunk_count'] += 1

    docs = list(groups.values())
    if tags:
        docs = [d for d in docs if any(t in d.get('tags', []) for t in tags)]

    return {"ok": True, "count": len(docs), "documents": docs[:limit]}


def kb_remove(doc_id: str) -> dict:
    """Remove a document (and all its chunks) from the knowledge base.

    Returns:
        {"ok": True, "removed": N}
    """
    idx = _load_index()
    entries = idx.get("entries", {})
    to_remove = [
        k for k, v in entries.items()
        if v.get('doc_id') == doc_id or v.get('group_id') == doc_id
    ]
    for k in to_remove:
        del entries[k]
    idx["entries"] = entries
    _save_index(idx)
    return {"ok": True, "removed": len(to_remove)}


def kb_clear() -> dict:
    """Clear the entire knowledge base.

    Returns:
        {"ok": True}
    """
    _save_index({"entries": {}})
    return {"ok": True}


def kb_stats() -> dict:
    """Get knowledge base statistics.

    Returns:
        {"ok": True, "documents": N, "chunks": N, "tags": [...], "has_embeddings": bool}
    """
    idx = _load_index()
    entries = idx.get("entries", {})
    all_tags = set()
    for e in entries.values():
        for t in e.get('tags', []):
            all_tags.add(t)
    has_emb = any('embedding' in e for e in entries.values())
    groups = set(e.get('group_id', k) for k, e in entries.items())
    return {
        "ok": True,
        "documents": len(groups),
        "chunks": len(entries),
        "tags": sorted(all_tags)[:100],
        "has_embeddings": has_emb,
        "storage_path": KB_DIR,
    }
