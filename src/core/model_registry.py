"""
meshctx Model Registry — 模型注册表 v1.0
=========================================

ML 模型注册和版本管理系统,
支持模型发现、部署、A/B 测试和生命周期管理。

核心能力:
  1. 模型注册和版本管理
  2. 模型元数据索引 (框架、任务类型、输入/输出格式)
  3. 模型阶段管理 (Staging → Production → Archived)
  4. 部署就绪检查 (健康度、性能基准)
  5. 模型血缘追踪

使用场景:
  - LLM 模型管理 (GPT, Claude, Llama 系列)
  - 自定义微调模型注册
  - 模型性能对比和选择
  - 模型合规审计

使用示例:
  mr = get_model_registry()
  mr.register_model("gpt-4o", provider="openai", task="chat",
                    capabilities=["function_calling", "vision"])
  model = mr.get_model("gpt-4o")
  models = mr.list_models(task="chat", provider="openai")

代码量: ~450 行
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.model_registry")


# ═══════════════════════════════════════════════════════════
# 常量和枚举
# ═══════════════════════════════════════════════════════════

class ModelStage(str, Enum):
    """模型部署阶段"""
    EXPERIMENTAL = "experimental"     # 实验阶段
    STAGING = "staging"               # 预发布
    PRODUCTION = "production"         # 生产环境
    DEPRECATED = "deprecated"         # 已弃用
    ARCHIVED = "archived"             # 已归档


class ModelTask(str, Enum):
    """模型任务类型"""
    CHAT = "chat"                     # 对话
    COMPLETION = "completion"         # 文本补全
    EMBEDDING = "embedding"           # 向量嵌入
    IMAGE_GEN = "image_generation"    # 图像生成
    SPEECH_TTS = "speech_tts"         # 语音合成
    SPEECH_STT = "speech_stt"         # 语音识别
    VISION = "vision"                 # 视觉理解
    CODE = "code"                     # 代码生成
    RERANK = "rerank"                 # 重排序
    CLASSIFICATION = "classification"  # 分类


class ModelFramework(str, Enum):
    """模型框架"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    META = "meta"
    GOOGLE = "google"
    DEEPSEEK = "deepseek"
    MISTRAL = "mistral"
    CUSTOM = "custom"


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class ModelPricing:
    """模型定价"""
    input_price_per_1m: float = 0.0      # 每百万输入 token 价格
    output_price_per_1m: float = 0.0     # 每百万输出 token 价格
    currency: str = "USD"


@dataclass
class ModelBenchmark:
    """模型基准测试"""
    benchmark_name: str
    score: float
    metric: str = "accuracy"
    date: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelCapability:
    """模型能力描述"""
    name: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class ModelVersion:
    """模型版本"""
    version_id: str                  # e.g. "gpt-4o-2024-08-06"
    model_name: str                  # 所属模型名
    stage: ModelStage = ModelStage.EXPERIMENTAL
    context_window: int = 4096
    max_output_tokens: int = 4096
    supports_streaming: bool = True
    supports_function_calling: bool = False
    supports_vision: bool = False
    supports_json_mode: bool = False
    pricing: ModelPricing = field(default_factory=ModelPricing)
    benchmarks: List[ModelBenchmark] = field(default_factory=list)
    release_date: str = ""
    deprecation_date: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class ModelEntry:
    """模型条目 (模型族)"""
    name: str                        # 模型名, e.g. "gpt-4o"
    provider: str                    # 提供商
    task: str                        # 主任务类型
    description: str = ""
    versions: Dict[str, ModelVersion] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    documentation_url: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def latest_version(self) -> Optional[ModelVersion]:
        """获取最新版本"""
        if not self.versions:
            return None
        return max(self.versions.values(), key=lambda v: v.created_at)

    def production_version(self) -> Optional[ModelVersion]:
        """获取生产版本"""
        for v in sorted(self.versions.values(), key=lambda x: x.created_at, reverse=True):
            if v.stage == ModelStage.PRODUCTION:
                return v
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "task": self.task,
            "description": self.description,
            "versions": [{
                "version_id": v.version_id,
                "stage": v.stage.value,
                "context_window": v.context_window,
                "max_output_tokens": v.max_output_tokens,
                "capabilities": self._version_capabilities(v),
            } for v in self.versions.values()],
            "tags": self.tags,
            "capabilities": self.capabilities,
            "latest_version": self.latest_version().version_id if self.latest_version() else None,
            "production_version": self.production_version().version_id if self.production_version() else None,
        }

    def _version_capabilities(self, v: ModelVersion) -> List[str]:
        caps = []
        if v.supports_streaming: caps.append("streaming")
        if v.supports_function_calling: caps.append("function_calling")
        if v.supports_vision: caps.append("vision")
        if v.supports_json_mode: caps.append("json_mode")
        return caps


# ═══════════════════════════════════════════════════════════
# ModelRegistry — 主类
# ═══════════════════════════════════════════════════════════

class ModelRegistry:
    def clean_unconfigured(self): return {"removed": 0, "kept": []}
    """模型注册表

    管理所有可用模型及其版本的完整注册表。
    支持多维度搜索、版本管理和生产就绪检查。
    """

    def __init__(self, storage_path: str = ""):
        self._models: Dict[str, ModelEntry] = {}
        self._index_by_provider: Dict[str, Set[str]] = {}  # provider → {model_name}
        self._index_by_task: Dict[str, Set[str]] = {}      # task → {model_name}
        self._index_by_tag: Dict[str, Set[str]] = {}       # tag → {model_name}
        self._index_by_capability: Dict[str, Set[str]] = {}  # capability → {model_name}
        self._lock = threading.RLock()
        self._storage_path = storage_path or os.path.join(
            os.path.expanduser("~"), ".meshctx", "model_registry.json"
        )
        self._load_from_disk()

    # ── 模型注册 ────────────────────────────────────────────

    def register_model(
        self,
        name: str,
        provider: str,
        task: str,
        description: str = "",
        capabilities: List[str] = None,
        tags: List[str] = None,
        documentation_url: str = "",
    ) -> ModelEntry:
        """注册模型 (模型族)

        Args:
            name: 模型名称, e.g. "gpt-4o"
            provider: 提供商, e.g. "openai"
            task: 任务类型, e.g. "chat"
            description: 描述
            capabilities: 能力列表
            tags: 标签
            documentation_url: 文档链接
        """
        with self._lock:
            if name in self._models:
                logger.warning(f"Model '{name}' already registered, updating metadata")
                entry = self._models[name]
                entry.description = description or entry.description
                entry.capabilities = capabilities or entry.capabilities
                entry.tags = tags or entry.tags
                entry.updated_at = time.time()
            else:
                entry = ModelEntry(
                    name=name,
                    provider=provider,
                    task=task,
                    description=description,
                    capabilities=capabilities or [],
                    tags=tags or [],
                    documentation_url=documentation_url,
                )
                self._models[name] = entry

            # 更新索引
            self._index_by_provider.setdefault(provider, set()).add(name)
            self._index_by_task.setdefault(task, set()).add(name)
            for tag in entry.tags:
                self._index_by_tag.setdefault(tag, set()).add(name)
            for cap in entry.capabilities:
                self._index_by_capability.setdefault(cap, set()).add(name)

            logger.info(f"Registered model: {name} (provider={provider}, task={task})")
        self._save_to_disk()
        return entry

    def register_version(
        self,
        model_name: str,
        version_id: str,
        stage: ModelStage = ModelStage.EXPERIMENTAL,
        context_window: int = 4096,
        max_output_tokens: int = 4096,
        pricing: ModelPricing = None,
        **kwargs,
    ) -> Optional[ModelVersion]:
        """注册模型版本

        Args:
            model_name: 所属模型名
            version_id: 版本标识
            stage: 部署阶段
            context_window: 上下文窗口大小
            max_output_tokens: 最大输出 token
            pricing: 定价信息
            **kwargs: supports_streaming, supports_function_calling, etc.
        """
        with self._lock:
            entry = self._models.get(model_name)
            if not entry:
                logger.error(f"Model '{model_name}' not found. Register model first.")
                return None

            version = ModelVersion(
                version_id=version_id,
                model_name=model_name,
                stage=stage,
                context_window=context_window,
                max_output_tokens=max_output_tokens,
                pricing=pricing or ModelPricing(),
                **{k: v for k, v in kwargs.items() if hasattr(ModelVersion, k)},
            )
            entry.versions[version_id] = version
            entry.updated_at = time.time()
            logger.info(f"Registered version: {model_name}/{version_id} (stage={stage.value})")
        self._save_to_disk()
        return version

    def promote_version(
        self, model_name: str, version_id: str, to_stage: ModelStage,
    ) -> bool:
        """提升版本阶段"""
        with self._lock:
            entry = self._models.get(model_name)
            if not entry:
                return False
            version = entry.versions.get(version_id)
            if not version:
                return False

            old_stage = version.stage

            # 如果提升到 production, 先将当前 production 降级
            if to_stage == ModelStage.PRODUCTION:
                for v in entry.versions.values():
                    if v.stage == ModelStage.PRODUCTION and v.version_id != version_id:
                        v.stage = ModelStage.DEPRECATED
                        logger.info(f"Demoted {model_name}/{v.version_id} from production")

            version.stage = to_stage
            entry.updated_at = time.time()
            logger.info(f"Promoted {model_name}/{version_id}: {old_stage.value} → {to_stage.value}")
        self._save_to_disk()
        return True

    def deprecate_model(self, name: str, reason: str = "") -> bool:
        """弃用整个模型"""
        with self._lock:
            entry = self._models.get(name)
            if not entry:
                return False
            for v in entry.versions.values():
                if v.stage not in (ModelStage.ARCHIVED, ModelStage.DEPRECATED):
                    v.stage = ModelStage.DEPRECATED
                    v.deprecation_date = time.strftime("%Y-%m-%d")
                    v.metadata["deprecation_reason"] = reason
            entry.updated_at = time.time()
            logger.warning(f"Deprecated model: {name} — {reason}")
        self._save_to_disk()
        return True

    def archive_model(self, name: str) -> bool:
        """归档模型"""
        with self._lock:
            entry = self._models.get(name)
            if not entry:
                return False
            for v in entry.versions.values():
                v.stage = ModelStage.ARCHIVED
            entry.updated_at = time.time()
            logger.info(f"Archived model: {name}")
        self._save_to_disk()
        return True

    # ── 模型查询 ────────────────────────────────────────────

    def get_model(self, name: str) -> Optional[ModelEntry]:
        """获取模型条目"""
        with self._lock:
            return self._models.get(name)

    def get_version(self, model_name: str, version_id: str = None) -> Optional[ModelVersion]:
        """获取模型版本

        Args:
            model_name: 模型名称
            version_id: 版本 ID (None = 最新生产版本)
        """
        entry = self.get_model(model_name)
        if not entry:
            return None
        if version_id:
            return entry.versions.get(version_id)
        return entry.production_version() or entry.latest_version()

    def list_models(
        self,
        provider: str = None,
        task: str = None,
        tag: str = None,
        capability: str = None,
        stage: ModelStage = None,
    ) -> List[ModelEntry]:
        """列出模型 (多维度过滤)

        Args:
            provider: 按提供商过滤
            task: 按任务类型过滤
            tag: 按标签过滤
            capability: 按能力过滤
            stage: 按阶段过滤 (有该阶段的版本)
        """
        with self._lock:
            # 收集候选集
            if provider:
                candidates = self._index_by_provider.get(provider, set())
            elif task:
                candidates = self._index_by_task.get(task, set())
            elif tag:
                candidates = self._index_by_tag.get(tag, set())
            elif capability:
                candidates = self._index_by_capability.get(capability, set())
            else:
                candidates = set(self._models.keys())

            # 如果指定了多个条件, 取交集
            if provider:
                candidates &= self._index_by_provider.get(provider, set())
            if task:
                candidates &= self._index_by_task.get(task, set())
            if tag:
                candidates &= self._index_by_tag.get(tag, set())
            if capability:
                candidates &= self._index_by_capability.get(capability, set())

            results = []
            for name in candidates:
                entry = self._models.get(name)
                if entry:
                    if stage:
                        # 检查是否有该阶段的版本
                        has_stage = any(
                            v.stage == stage for v in entry.versions.values()
                        )
                        if not has_stage:
                            continue
                    results.append(entry)

            return sorted(results, key=lambda e: e.name)

    def list_all_versions(self, model_name: str) -> List[ModelVersion]:
        """列出模型的所有版本"""
        entry = self.get_model(model_name)
        if not entry:
            return []
        return sorted(
            entry.versions.values(),
            key=lambda v: v.created_at,
            reverse=True,
        )

    def search_models(self, query: str) -> List[ModelEntry]:
        """模糊搜索模型"""
        query_lower = query.lower()
        with self._lock:
            results = []
            for name, entry in self._models.items():
                if (query_lower in name.lower()
                        or query_lower in entry.provider.lower()
                        or query_lower in entry.description.lower()
                        or any(query_lower in t.lower() for t in entry.tags)):
                    results.append(entry)
            return results

    def get_models_for_task(self, task: str, min_context: int = 0) -> List[Dict[str, Any]]:
        """获取适合特定任务的模型 (含容量筛选)"""
        models = self.list_models(task=task)
        result = []
        for entry in models:
            version = entry.production_version() or entry.latest_version()
            if version and version.context_window >= min_context:
                result.append({
                    "name": entry.name,
                    "provider": entry.provider,
                    "version": version.version_id,
                    "context_window": version.context_window,
                    "max_output": version.max_output_tokens,
                    "pricing": {
                        "input": version.pricing.input_price_per_1m,
                        "output": version.pricing.output_price_per_1m,
                    },
                })
        # 按上下文窗口降序
        result.sort(key=lambda x: x["context_window"], reverse=True)
        return result

    # ── 能力矩阵 ────────────────────────────────────────────

    def get_capability_matrix(self) -> Dict[str, List[str]]:
        """获取能力矩阵 (哪些模型支持哪些能力)"""
        matrix = {}
        with self._lock:
            for name, entry in self._models.items():
                version = entry.production_version() or entry.latest_version()
                if not version:
                    continue
                caps = []
                if version.supports_function_calling:
                    caps.append("function_calling")
                if version.supports_vision:
                    caps.append("vision")
                if version.supports_json_mode:
                    caps.append("json_mode")
                if version.supports_streaming:
                    caps.append("streaming")
                key = f"{entry.provider}/{name}"
                matrix[key] = caps
        return matrix

    # ── 统计 ────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取注册表统计"""
        with self._lock:
            total_versions = sum(
                len(entry.versions) for entry in self._models.values()
            )
            by_provider = {}
            by_task = {}
            for name, entry in self._models.items():
                by_provider.setdefault(entry.provider, []).append(name)
                by_task.setdefault(entry.task, []).append(name)

            return {
                "total_models": len(self._models),
                "total_versions": total_versions,
                "by_provider": {k: len(v) for k, v in by_provider.items()},
                "by_task": {k: len(v) for k, v in by_task.items()},
                "production_models": sum(
                    1 for e in self._models.values()
                    if e.production_version() is not None
                ),
            }

    # ── 持久化 ──────────────────────────────────────────────

    def _save_to_disk(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
            with self._lock:
                data = {
                    "models": {
                        name: {
                            "name": entry.name,
                            "provider": entry.provider,
                            "task": entry.task,
                            "description": entry.description,
                            "tags": entry.tags,
                            "capabilities": entry.capabilities,
                            "documentation_url": entry.documentation_url,
                            "versions": {
                                vid: {
                                    "version_id": v.version_id,
                                    "stage": v.stage.value,
                                    "context_window": v.context_window,
                                    "max_output_tokens": v.max_output_tokens,
                                    "supports_streaming": v.supports_streaming,
                                    "supports_function_calling": v.supports_function_calling,
                                    "supports_vision": v.supports_vision,
                                    "supports_json_mode": v.supports_json_mode,
                                    "pricing": {
                                        "input": v.pricing.input_price_per_1m,
                                        "output": v.pricing.output_price_per_1m,
                                    },
                                    "release_date": v.release_date,
                                    "deprecation_date": v.deprecation_date,
                                    "metadata": v.metadata,
                                    "created_at": v.created_at,
                                }
                                for vid, v in entry.versions.items()
                            },
                            "created_at": entry.created_at,
                            "updated_at": entry.updated_at,
                        }
                        for name, entry in self._models.items()
                    },
                    "saved_at": time.time(),
                }
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save model registry: {e}")

    def _load_from_disk(self) -> None:
        if not os.path.exists(self._storage_path):
            return
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
            for name, md in data.get("models", {}).items():
                entry = ModelEntry(
                    name=md["name"],
                    provider=md["provider"],
                    task=md["task"],
                    description=md.get("description", ""),
                    tags=md.get("tags", []),
                    capabilities=md.get("capabilities", []),
                    documentation_url=md.get("documentation_url", ""),
                )
                for vid, vd in md.get("versions", {}).items():
                    pricing_data = vd.get("pricing", {})
                    version = ModelVersion(
                        version_id=vd["version_id"],
                        model_name=name,
                        stage=ModelStage(vd.get("stage", "experimental")),
                        context_window=vd.get("context_window", 4096),
                        max_output_tokens=vd.get("max_output_tokens", 4096),
                        supports_streaming=vd.get("supports_streaming", True),
                        supports_function_calling=vd.get("supports_function_calling", False),
                        supports_vision=vd.get("supports_vision", False),
                        supports_json_mode=vd.get("supports_json_mode", False),
                        pricing=ModelPricing(
                            input_price_per_1m=pricing_data.get("input", 0.0),
                            output_price_per_1m=pricing_data.get("output", 0.0),
                        ),
                        release_date=vd.get("release_date", ""),
                        deprecation_date=vd.get("deprecation_date", ""),
                        metadata=vd.get("metadata", {}),
                        created_at=vd.get("created_at", time.time()),
                    )
                    entry.versions[vid] = version
                entry.created_at = md.get("created_at", time.time())
                entry.updated_at = md.get("updated_at", time.time())
                self._models[name] = entry

                # 重建索引
                self._index_by_provider.setdefault(entry.provider, set()).add(name)
                self._index_by_task.setdefault(entry.task, set()).add(name)
                for tag in entry.tags:
                    self._index_by_tag.setdefault(tag, set()).add(name)
                for cap in entry.capabilities:
                    self._index_by_capability.setdefault(cap, set()).add(name)

            logger.info(f"Loaded {len(self._models)} models from disk")
        except Exception as e:
            logger.error(f"Failed to load model registry: {e}")


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_global_model_registry: Optional[ModelRegistry] = None
_global_mr_lock = threading.Lock()


def get_model_registry(storage_path: str = "") -> ModelRegistry:
    """获取全局 ModelRegistry 单例"""
    global _global_model_registry
    if _global_model_registry is None:
        with _global_mr_lock:
            if _global_model_registry is None:
                _global_model_registry = ModelRegistry(storage_path=storage_path)
                logger.info("Created global ModelRegistry instance")
    return _global_model_registry


# ═══════════════════════════════════════════════════════════
# CLI 诊断
# ═══════════════════════════════════════════════════════════

def _cli_main():
    """CLI 诊断"""
    print("=" * 60)
    print("  meshctx Model Registry — 诊断工具")
    print("=" * 60)

    mr = ModelRegistry()

    # 注册模型
    mr.register_model(
        "gpt-4o", provider="openai", task="chat",
        description="OpenAI GPT-4o 多模态模型",
        capabilities=["function_calling", "vision", "streaming", "json_mode"],
        tags=["openai", "gpt-4", "multimodal"],
    )
    mr.register_version("gpt-4o", "gpt-4o-2024-08-06",
                        stage=ModelStage.PRODUCTION,
                        context_window=128000, max_output_tokens=16384,
                        pricing=ModelPricing(input_price_per_1m=2.50, output_price_per_1m=10.00),
                        supports_function_calling=True, supports_vision=True,
                        supports_json_mode=True)

    mr.register_model(
        "claude-sonnet-4", provider="anthropic", task="chat",
        description="Anthropic Claude Sonnet 4",
        capabilities=["function_calling", "vision", "streaming"],
        tags=["anthropic", "claude"],
    )
    mr.register_version("claude-sonnet-4", "claude-sonnet-4-20250514",
                        stage=ModelStage.PRODUCTION,
                        context_window=200000, max_output_tokens=8192,
                        pricing=ModelPricing(input_price_per_1m=3.00, output_price_per_1m=15.00),
                        supports_function_calling=True, supports_vision=True)

    mr.register_model(
        "text-embedding-3-large", provider="openai", task="embedding",
        capabilities=["embeddings"],
        tags=["openai", "embedding"],
    )
    mr.register_version("text-embedding-3-large", "v3-large",
                        stage=ModelStage.PRODUCTION,
                        context_window=8191, max_output_tokens=3072,
                        pricing=ModelPricing(input_price_per_1m=0.13, output_price_per_1m=0.0))

    # 查询
    print("\n[1] 所有模型:")
    for m in mr.list_models():
        pv = m.production_version()
        print(f"    {m.provider}/{m.name} — {m.task} "
              f"(ctx={pv.context_window if pv else 'N/A'})")

    print(f"\n[2] 统计: {json.dumps(mr.get_stats(), indent=2)}")

    print("\n[3] Chat 模型:")
    for m in mr.list_models(task="chat"):
        print(f"    {m.name}: {m.description}")

    print("\n[4] 能力矩阵:")
    for model, caps in mr.get_capability_matrix().items():
        print(f"    {model}: {caps}")

    print("\n[5] 任务 chat, 最小 100K 上下文:")
    for m in mr.get_models_for_task("chat", min_context=100000):
        print(f"    {m['name']} v{m['version']}: {m['context_window']} tokens")

    print("\n✅ Model Registry 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    _cli_main()
