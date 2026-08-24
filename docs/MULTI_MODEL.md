# MeshCtx 多模型接入指南（模型无关记忆架构）

> 核心设计原则：**记忆系统与模型解耦**。MeshCtx 支持全世界主流模型接入，
> 测试时不必用最强模型——记忆架构的增益与具体模型无关，用当前模型即可获得优秀结果。

## 1. 设计理念

- **模型无关**：记忆检索、FSRS 调度、注入排序等核心逻辑不依赖任何特定模型 API。
- **统一协议**：所有模型走 OpenAI 兼容 chat 协议（各厂商已提供兼容端点）。
- **配置驱动**：模型切换只改环境变量 `MODEL_ID`，代码零改动。

## 2. 支持的模型（122 个已注册，src/model_registry.py）

| 家族 | 模型 ID 示例 | key 环境变量 |
|---|---|---|
| OpenAI | `openai:gpt-4o` / `openai:gpt-5` / `openai:gpt-5-mini` / `openai:gpt-5-pro` | `OPENAI_API_KEY` |
| Anthropic | `anthropic:claude-sonnet` / `anthropic:claude-opus` | `ANTHROPIC_API_KEY` |
| Google | `google:gemini-pro` / `google:gemini-flash` | `GEMINI_API_KEY` |
| xAI | `xai:grok-3`（grok-4.6） | `XAI_API_KEY` |
| OpenRouter | `openrouter:gpt-4o` / `openrouter:claude-sonnet` / `openrouter:gemini-pro` / `openrouter:llama-4`（200+ 模型统一网关） | `OPENROUTER_API_KEY` |
| DeepSeek | `deepseek:v4-flash` / `deepseek:v4-pro` / `deepseek:v4-flash-vision`（chat/reasoner 兼容映射） | `DEEPSEEK_API_KEY` |
| 阿里 Qwen | `bailian:qwen3-max` / `bailian:qwen3-plus` / `bailian:qwen-flash` | `BAILIAN_API_KEY` |
| 智谱 GLM | `zhipu:glm-4-plus` / `zhipu:glm-4-flash` | `ZHIPU_API_KEY` |
| 月之暗面 Kimi | `moonshot:kimi` / `moonshot:kimi-k3` | `MOONSHOT_API_KEY` |
| 字节豆包 | `doubao:pro-128k` / `doubao:lite` | `DOUBAO_API_KEY` |
| 腾讯混元 | `hunyuan:pro` / `hunyuan:lite` | `HUNYUAN_API_KEY` |
| 讯飞星火 | `spark:max` / `spark:pro` | `SPARK_API_KEY` |
| Perplexity | `perplexity:sonar-pro` | `PERPLEXITY_API_KEY` |
| Together | `together:llama-4-maverick` | `TOGETHER_API_KEY` |

查看全部：`python3 -m src.cli models list`（或 `python3 -c "from src.model_registry import BUILTIN_MODELS; print(len(BUILTIN_MODELS))"`）。

## 3. 接入配置

每个模型只需配置对应 `key` 环境变量（`.env` 或系统环境**均可**）。
`model_io` 按 `model_registry.BUILTIN_MODELS` 的 `key_env` 字段自动解析**任意 provider** 的 key：

```bash
# .env 示例（任意 provider 的 key 都能被自动读取）
DEEPSEEK_API_KEY=sk-xxx
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-xxx
GEMINI_API_KEY=sk-xxx
XAI_API_KEY=sk-xxx
OPENROUTER_API_KEY=sk-xxx
QWEN_API_KEY=sk-xxx
GLM_API_KEY=sk-xxx
MOONSHOT_API_KEY=sk-xxx
DOUBAO_API_KEY=sk-xxx
HUNYUAN_API_KEY=sk-xxx
SPARK_API_KEY=sk-xxx
```

> 说明：key 缺省时 `model_io` 还会回退尝试 `OPENAI_API_KEY`/`DEEPSEEK_API_KEY`
> 这类 OpenAI 兼容通用 key；仍无则抛 `RuntimeError` 明确报错（不静默）。

自定义模型（一行注册）：

```python
from src.model_registry import ModelRegistry
reg = ModelRegistry()
reg.add("my:model", key="sk-xxx", model="my-model", base_url="https://my-gateway/v1")
```

## 4. 评测切换模型（benchmarks/longmemeval）

所有 LongMemEval runner 通过 `benchmarks/longmemeval/model_io.py` 统一接入：

```bash
# 默认：deepseek:chat（测试用当前模型即可）
python3 benchmarks/longmemeval/run_meshctx_memory.py

# 切换任意主流模型，评测代码零改动
MODEL_ID=openrouter:gpt-4o      python3 benchmarks/longmemeval/run_meshctx_memory.py
MODEL_ID=anthropic:claude-sonnet python3 benchmarks/longmemeval/run_meshctx_memory.py
MODEL_ID=google:gemini-flash    python3 benchmarks/longmemeval/run_meshctx_memory.py
MODEL_ID=bailian:qwen3-plus     python3 benchmarks/longmemeval/run_meshctx_memory.py
MODEL_ID=deepseek:reasoner      python3 benchmarks/longmemeval/run_meshctx_memory.py
```

已验证：`MODEL_ID=deepseek:chat` 与 `MODEL_ID=deepseek:reasoner` 切换均正常（探针 EM 与历史一致）。

## 5. 为什么「测试不必用最强模型」

LongMemEval 48Q 三探针证据链（2026-08-20，commit 05d81f2）：

| 模式 | EM | 结论 |
|---|---|---|
| 全量基线（deepseek-chat） | 52.1% | 当前最优 |
| reasoner 全量 | 50.0% | 同代际换模型无增益 |
| oracle 检索上限 | 47.9% | 检索非瓶颈 |
| 提示词逐字引述 | 29.2% | 引述指令反噬 |

结论：**记忆架构优化（模型无关）才是结果提升的关键**。预算场景已验证
P2 注入用 13KB 达到全量 29KB 的准确率（EM=41.7%，+16.7pp vs 暴力截断）。
