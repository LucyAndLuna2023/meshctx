"""
meshctx 向量存储 — 支持 ChromaDB / 轻量numpy回退
"""
import os
import json
import uuid
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime

# 数据目录
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "vectors")
os.makedirs(DATA_DIR, exist_ok=True)


class VectorStore:
    """统一向量存储接口"""

    def __init__(self, backend: str = "auto"):
        self.backend_name = backend
        self._store = None
        self._collection = None
        self._init_backend()

    def _init_backend(self):
        if self.backend_name == "auto":
            try:
                import chromadb
                self._init_chroma()
                return
            except ImportError:
                pass
        self._init_numpy()

    def _init_chroma(self):
        import chromadb
        self._store = chromadb.PersistentClient(path=DATA_DIR)
        self._collection = self._store.get_or_create_collection("meshctx_memories")
        self.backend_name = "chromadb"

    def _init_numpy(self):
        self._index_file = os.path.join(DATA_DIR, "numpy_index.json")
        self._vectors: List[Dict] = []
        self._load_numpy_index()
        self.backend_name = "numpy"

    def _load_numpy_index(self):
        if os.path.exists(self._index_file):
            with open(self._index_file, "r", encoding="utf-8") as f:
                self._vectors = json.load(f)

    def _save_numpy_index(self):
        with open(self._index_file, "w", encoding="utf-8") as f:
            json.dump(self._vectors, f, ensure_ascii=False, indent=2, default=str)

    def add(self, text: str, embedding: List[float], metadata: Dict[str, Any] = None) -> str:
        doc_id = str(uuid.uuid4())
        if self.backend_name == "chromadb":
            self._collection.add(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[metadata or {}]
            )
        else:
            self._vectors.append({
                "id": doc_id,
                "text": text,
                "embedding": embedding,
                "metadata": metadata or {},
                "timestamp": datetime.now().isoformat()
            })
            self._save_numpy_index()
        return doc_id

    def search(self, query_embedding: List[float], top_k: int = 5,
               filter_project: str = None) -> List[Dict]:
        if self.backend_name == "chromadb":
            where = {"project_id": filter_project} if filter_project else None
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where
            )
            return [
                {
                    "id": results["ids"][0][i],
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "score": 1 - results["distances"][0][i]
                }
                for i in range(len(results["ids"][0]))
            ]
        else:
            # NumPy余弦相似度
            import numpy as np
            if not self._vectors:
                return []
            query = np.array(query_embedding)
            scores = []
            for v in self._vectors:
                if filter_project and v.get("metadata", {}).get("project_id") != filter_project:
                    continue
                vec = np.array(v["embedding"])
                sim = np.dot(query, vec) / (np.linalg.norm(query) * np.linalg.norm(vec) + 1e-10)
                scores.append((sim, v))
            scores.sort(key=lambda x: x[0], reverse=True)
            return [
                {
                    "id": v["id"],
                    "text": v["text"],
                    "metadata": v["metadata"],
                    "score": float(s)
                }
                for s, v in scores[:top_k]
            ]

    def delete(self, doc_id: str):
        if self.backend_name == "chromadb":
            self._collection.delete(ids=[doc_id])
        else:
            self._vectors = [v for v in self._vectors if v["id"] != doc_id]
            self._save_numpy_index()

    def count(self) -> int:
        if self.backend_name == "chromadb":
            return self._collection.count()
        return len(self._vectors)


class EmbeddingEngine:
    """嵌入向量生成引擎"""

    def __init__(self, model_name: str = "auto"):
        self.model = None
        self.model_name = model_name
        self._init_model()

    def _init_model(self):
        if self.model_name == "auto":
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer("all-MiniLM-L6-v2")
                self.model_name = "all-MiniLM-L6-v2"
                return
            except ImportError:
                pass
        # 回退：简单hash向量（32维）
        self.model_name = "hash32"

    def encode(self, text: str) -> List[float]:
        if self.model is not None:
            return self.model.encode(text).tolist()
        # Hash回退
        h = hashlib.sha256(text.encode()).digest()
        vec = []
        for i in range(0, 32, 4):
            val = int.from_bytes(h[i:i+4], 'big') / (2**32) * 2 - 1
            vec.append(float(val))
        return vec

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        if self.model is not None:
            return self.model.encode(texts).tolist()
        return [self.encode(t) for t in texts]


# 全局单例
_vector_store: Optional[VectorStore] = None
_embedding_engine: Optional[EmbeddingEngine] = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store


def get_embedding_engine() -> EmbeddingEngine:
    global _embedding_engine
    if _embedding_engine is None:
        _embedding_engine = EmbeddingEngine()
    return _embedding_engine
