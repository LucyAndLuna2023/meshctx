"""
MeshCtx Memory Engine — 连续上下文记忆核心引擎

提供跨会话的持久化上下文记忆功能：
- CrossPlatformEngine: 跨平台持久化存储 (SQLite)
- VectorStore: 语义向量存储与相似度搜索
- LLMExtractor: 基于LLM的关键信息抽取
- MemoryEngine: 统一编排层
"""

import json
import os
import sqlite3
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from pathlib import Path

import numpy as np

logger = logging.getLogger("meshctx.engine")

# ──────────────────────────────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────────────────────────────
DEFAULT_DATA_DIR = Path(os.environ.get("MESHCTX_DATA_DIR", Path(__file__).parent.parent / "data"))
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "meshctx.db"
DEFAULT_VECTOR_DIM = 384  # all-MiniLM-L6-v2 输出维度


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


# ──────────────────────────────────────────────────────────────────────
# CrossPlatformEngine — SQLite 持久化存储
# ──────────────────────────────────────────────────────────────────────
class CrossPlatformEngine:
    """跨平台 SQLite 存储引擎，支持 Linux / Windows / macOS。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        _ensure_dir(self.db_path.parent)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                role        TEXT NOT NULL DEFAULT 'user',
                content     TEXT NOT NULL,
                metadata    TEXT DEFAULT '{}',
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_messages_project ON messages(project_id, created_at);

            CREATE TABLE IF NOT EXISTS facts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                fact        TEXT NOT NULL,
                confidence  REAL NOT NULL DEFAULT 1.0,
                source_msg  INTEGER REFERENCES messages(id) ON DELETE SET NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_facts_project ON facts(project_id);
        """)
        self._conn.commit()

    # ── 项目操作 ──────────────────────────────────────────────────

    def ensure_project(self, project_id: str, name: str = "") -> dict:
        self._conn.execute(
            "INSERT INTO projects(id, name) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET updated_at=datetime('now')",
            (project_id, name),
        )
        self._conn.commit()
        return {"id": project_id, "name": name}

    def list_projects(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, created_at, updated_at FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_project(self, project_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ── 消息操作 ──────────────────────────────────────────────────

    def save(self, project_id: str, content: str, role: str = "user", metadata: dict | None = None) -> int:
        """保存一条消息，返回消息ID。"""
        self.ensure_project(project_id)
        cur = self._conn.execute(
            "INSERT INTO messages(project_id, role, content, metadata) VALUES(?,?,?,?)",
            (project_id, role, content, json.dumps(metadata or {})),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_messages(
        self, project_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, project_id, role, content, metadata, created_at "
            "FROM messages WHERE project_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (project_id, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def search_messages(self, project_id: str, keyword: str, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, project_id, role, content, metadata, created_at "
            "FROM messages WHERE project_id=? AND content LIKE ? ORDER BY created_at DESC LIMIT ?",
            (project_id, f"%{keyword}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_message_count(self, project_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE project_id=?", (project_id,)
        ).fetchone()
        return row["cnt"]

    # ── 事实操作 ──────────────────────────────────────────────────

    def save_fact(self, project_id: str, fact: str, confidence: float = 1.0, source_msg: int | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO facts(project_id, fact, confidence, source_msg) VALUES(?,?,?,?)",
            (project_id, fact, confidence, source_msg),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_facts(self, project_id: str, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, project_id, fact, confidence, source_msg, created_at "
            "FROM facts WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self._conn.close()


# ──────────────────────────────────────────────────────────────────────
# VectorStore — 语义向量存储 (numpy + 余弦相似度)
# ──────────────────────────────────────────────────────────────────────
class VectorStore:
    """轻量级向量存储，使用 numpy 实现余弦相似度搜索。
    支持 sentence-transformers 作为可选后端以获得更好的语义质量。
    """

    def __init__(self, dim: int = DEFAULT_VECTOR_DIM):
        self.dim = dim
        self._vectors: dict[str, np.ndarray] = {}       # key -> vector
        self._metadata: dict[str, dict] = {}             # key -> metadata
        self._encoder = None
        self._try_load_encoder()

    def _try_load_encoder(self):
        """尝试加载 sentence-transformers，成功则启用语义编码。"""
        try:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer("all-MiniLM-L6-v2")
            self.dim = self._encoder.get_sentence_embedding_dimension()
            logger.info("VectorStore: sentence-transformers encoder loaded (dim=%d)", self.dim)
        except ImportError:
            logger.info("VectorStore: sentence-transformers not available, using random vectors (dim=%d)", self.dim)

    def _encode(self, text: str) -> np.ndarray:
        if self._encoder:
            vec = self._encoder.encode([text], normalize_embeddings=True)[0]
            return vec.astype(np.float32)
        else:
            # Fallback: 基于文本哈希生成确定性向量（用于开发测试）
            h = hashlib.sha256(text.encode()).digest()
            seed = int.from_bytes(h[:4], "big")
            rng = np.random.RandomState(seed)
            vec = rng.randn(self.dim).astype(np.float32)
            vec /= np.linalg.norm(vec) + 1e-8
            return vec

    def _make_key(self, project_id: str, item_id: str) -> str:
        return f"{project_id}::{item_id}"

    def add(self, project_id: str, text: str, item_id: str | None = None, metadata: dict | None = None) -> str:
        """添加文本到向量存储，返回 key。"""
        vec = self._encode(text)
        key = item_id or hashlib.md5(f"{project_id}:{text}:{datetime.now().isoformat()}".encode()).hexdigest()[:16]
        full_key = self._make_key(project_id, key)
        self._vectors[full_key] = vec
        self._metadata[full_key] = {
            "project_id": project_id,
            "text": text[:500],
            "added_at": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }
        return key

    def search(self, project_id: str, query: str, top_k: int = 10) -> list[dict]:
        """语义搜索，返回 top_k 最相似结果。"""
        query_vec = self._encode(query)
        prefix = f"{project_id}::"

        scores = []
        for key, vec in self._vectors.items():
            if not key.startswith(prefix):
                continue
            sim = float(np.dot(query_vec, vec) / (np.linalg.norm(query_vec) * np.linalg.norm(vec) + 1e-8))
            scores.append((key, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        results = []
        for key, sim in scores[:top_k]:
            meta = dict(self._metadata.get(key, {}))
            meta["key"] = key
            meta["similarity"] = round(sim, 4)
            results.append(meta)
        return results

    def delete_project(self, project_id: str):
        prefix = f"{project_id}::"
        keys = [k for k in self._vectors if k.startswith(prefix)]
        for k in keys:
            del self._vectors[k]
            self._metadata.pop(k, None)

    def stats(self) -> dict:
        return {"total_vectors": len(self._vectors), "dimension": self.dim}


# ──────────────────────────────────────────────────────────────────────
# LLMExtractor — LLM 关键信息抽取
# ──────────────────────────────────────────────────────────────────────
class LLMExtractor:
    """使用 LLM 从消息中抽取结构化关键信息。

    支持 OpenAI 兼容 API，可通过环境变量配置：
    - LLM_API_KEY: API 密钥
    - LLM_BASE_URL: API 地址 (默认 https://api.openai.com/v1)
    - LLM_MODEL: 模型名称 (默认 gpt-3.5-turbo)
    """

    EXTRACTION_PROMPT = """From the following message, extract key facts, decisions, preferences, 
and important context that should be remembered across sessions.
Return ONLY a JSON array of strings, each string being one fact.
If nothing significant, return an empty array [].

Message: {message}

Output (JSON array only):"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.base_url = base_url or os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model = model or os.environ.get("LLM_MODEL", "gpt-3.5-turbo")
        self._enabled = bool(self.api_key)

    def extract_key_information(self, message: str) -> list[str]:
        """从消息中抽取关键信息，返回事实列表。"""
        if not self._enabled:
            logger.debug("LLMExtractor: no API key configured, skipping extraction")
            return self._rule_based_extract(message)

        try:
            import requests
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You are a precise fact extractor. Respond only with valid JSON."},
                        {"role": "user", "content": self.EXTRACTION_PROMPT.format(message=message)},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500,
                },
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            # 提取 JSON 数组
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            facts = json.loads(content)
            return facts if isinstance(facts, list) else []
        except Exception as e:
            logger.warning("LLMExtractor: API call failed (%s), falling back to rule-based", e)
            return self._rule_based_extract(message)

    def _rule_based_extract(self, message: str) -> list[str]:
        """规则兜底：简单关键词抽取。"""
        facts = []
        triggers = {
            "name is": "user_name",
            "I am": "user_identity",
            "I prefer": "user_preference",
            "I want": "user_intent",
            "remember": "memory_request",
            "don't": "user_aversion",
            "project is": "project_info",
        }
        msg_lower = message.lower()
        for phrase, category in triggers.items():
            if phrase in msg_lower:
                idx = msg_lower.index(phrase)
                snippet = message[idx : idx + 120].strip()
                facts.append(f"[{category}] {snippet}")
        return facts


# ──────────────────────────────────────────────────────────────────────
# MemoryEngine — 统一编排层
# ──────────────────────────────────────────────────────────────────────
class MemoryEngine:
    """上下文记忆引擎 — 编排存储、向量化和抽取的完整流程。

    用法:
        engine = MemoryEngine()
        engine.add_message("I prefer Python over JavaScript", project_id="myapp")
        context = engine.get_context("myapp", limit=10)
        results = engine.search("myapp", "Python")
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        vector_dim: int = DEFAULT_VECTOR_DIM,
        llm_api_key: str | None = None,
        llm_base_url: str | None = None,
        llm_model: str | None = None,
    ):
        self.cross_platform_engine = CrossPlatformEngine(db_path=db_path)
        self.vector_store = VectorStore(dim=vector_dim)
        self.llm_extractor = LLMExtractor(
            api_key=llm_api_key,
            base_url=llm_base_url,
            model=llm_model,
        )

    # ── 核心 API ──────────────────────────────────────────────────

    def add_message(
        self,
        content: str,
        project_id: str,
        role: str = "user",
        metadata: dict | None = None,
    ) -> dict:
        """添加消息，自动存储、向量化和抽取关键信息。"""
        # 1. 持久化存储
        msg_id = self.cross_platform_engine.save(project_id, content, role, metadata)

        # 2. 向量化
        vec_key = self.vector_store.add(project_id, content, item_id=str(msg_id))

        # 3. LLM 抽取关键事实
        facts = self.llm_extractor.extract_key_information(content)
        for fact in facts:
            self.cross_platform_engine.save_fact(project_id, fact, source_msg=msg_id)

        return {
            "message_id": msg_id,
            "project_id": project_id,
            "vector_key": vec_key,
            "facts_extracted": len(facts),
            "facts": facts,
        }

    def get_context(
        self,
        project_id: str,
        limit: int = 20,
        include_facts: bool = True,
    ) -> dict:
        """获取项目的完整上下文 — 最近消息 + 抽取的事实。"""
        messages = self.cross_platform_engine.get_messages(project_id, limit=limit)
        facts = self.cross_platform_engine.get_facts(project_id) if include_facts else []
        return {
            "project_id": project_id,
            "message_count": self.cross_platform_engine.get_message_count(project_id),
            "recent_messages": messages,
            "extracted_facts": facts,
        }

    def search(
        self,
        project_id: str,
        query: str,
        top_k: int = 10,
    ) -> dict:
        """语义搜索 + 关键词搜索的融合结果。"""
        semantic_results = self.vector_store.search(project_id, query, top_k=top_k)
        keyword_results = self.cross_platform_engine.search_messages(project_id, query, limit=top_k)
        return {
            "query": query,
            "semantic_matches": semantic_results,
            "keyword_matches": [dict(r) for r in keyword_results],
        }

    def list_projects(self) -> list[dict]:
        return self.cross_platform_engine.list_projects()

    def delete_project(self, project_id: str) -> dict:
        deleted_db = self.cross_platform_engine.delete_project(project_id)
        self.vector_store.delete_project(project_id)
        return {"project_id": project_id, "deleted": deleted_db}

    def stats(self) -> dict:
        return {
            "db_path": str(self.cross_platform_engine.db_path),
            "projects": len(self.list_projects()),
            "vector_store": self.vector_store.stats(),
        }

    def close(self):
        self.cross_platform_engine.close()


# ──────────────────────────────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────────────────────────────
_engine: Optional[MemoryEngine] = None


def get_engine(**kwargs) -> MemoryEngine:
    global _engine
    if _engine is None:
        _engine = MemoryEngine(**kwargs)
    return _engine
