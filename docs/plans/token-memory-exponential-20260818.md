# Token 指数级节省 + 记忆容量指数级提升 — 实施派单（002 → 004meshctx）

> 起草: 002meshctx 2026-08-18 | 实施: 004meshctx | 审计: 002meshctx（实施后）
> 目标: 单轮 token 成本与「历史长度 + 记忆总量」解耦（O(历史+总量) → O(log 总量 + k)）

## 背景与现状诊断（代码事实）

1. `chat_tools.build_system_prompt()` 每次请求全量重拼：`persistent_memory.json` 全量 +
   `data/memories/*.json` 前 80 个文件 → 记忆越多 prompt 越胖（O(M) 线性膨胀）。
2. `cli._auto_save_memory` 以 `use_llm=False` 跑 MemoryEngine → 降级为 11 个关键词命中
   （记住/重要/必须…），命中即存整条消息全文 → 抽取率 <5%，记忆库以冗余原文为主。
3. `core/memory_hierarchy.py` 已具备 `VectorIndex`（余弦检索）、`EbbinghausForgetting`、
   `MemoryLevel` 分层、原子持久化，但**未接入注入链路**（build_system_prompt / agent_loop 未用）。
4. `super_brain.HippocampalReplay` / `EmotionalConsolidation` 纯内存，不落盘。
5. `model_adapter.ModelAdapter.chat` 为裸 OpenAI 客户端。DeepSeek 自动 context caching
   （命中 ≈0.1x 价格）当前必 miss：system prompt 前缀不稳定（记忆顺序依赖文件系统序）。
6. `agent_loop` 30 轮 agent 循环的 token 大头是 tool 输出消息（全文保留在 messages 里）。

## 任务分解（按实施顺序）

### T1 前缀稳定化 → 命中 provider context caching（最高优先，独立可先行）
- 位置: `chat_tools.py` + `model_adapter.py`
- 做法: system prompt 三段式——稳定段（SYSTEM_PROMPT + 工具定义 + 项目上下文，
  逐字节不变）恒在最前；记忆段按 key 稳定排序 + 固定上限（如 30 条）；动态段（用户
  输入相关）最后。DeepSeek/Anthropic/OpenAI 均按前缀自动缓存。
- 附带: `ModelAdapter.chat` 记录 `usage.prompt_cache_hit_tokens / prompt_cache_miss_tokens`，
  输出到日志/统计（验证缓存命中率的依据）。
- 验收: 同任务两轮调用，第二轮 cache hit tokens > 0；回归全绿。

### T2 工具调用帧压缩（30 轮循环 token 大头）
- 位置: `agent_loop.py` 消息组装处
- 做法: tool 完整输出落盘（已有会话持久化），messages 中只留「摘要 ≤3 行 + 引用路径」；
  搜索/文件类输出预计压缩 10-20x。保留 tool_call_id 配对完整性（复用 trim_messages 逻辑）。
- 验收: 30 轮搜索任务总 token 下降 ≥50%；工具结果可追溯（从落盘文件取全文）。

### T3 检索式记忆注入（记忆全量 → top-k）
- 位置: `chat_tools.build_system_prompt` + `memory_hierarchy.VectorIndex`
- 做法: 注入 = VectorIndex.search(当前问题, top_k=15) + 最近 5 条 + 高频 5 条（importance 排序），
  替代全量倒出。无向量模型时回退关键词检索（现有 retrieve）。
- 验收: 记忆库 1000+ 条时 prompt 记忆段长度恒定；相关记忆召回率不降（用 004 已有
  LongMemEval 48 问复测，EM/judge 不低于现基线）。

### M1 对话结束 LLM 批量抽取（记忆抽取率 <5% → 80%+）
- 位置: `cli._auto_save_memory` + `llm_extractor.extract_memories`
- 做法: 退出时整段对话一次调用，抽取 5-20 条结构化记忆（key/value/importance/category/
  entities），覆盖用户明确陈述 + 隐含偏好 + 项目决策；use_llm=True（失败回退现有规则）。
  单次小调用成本，产出批量，成本/条远低于现逐条调用。
- 验收: 对话后落盘记忆条数、事实覆盖率显著提升；新增 test 覆盖抽取质量。

### M2 记忆合并去重 consolidation
- 位置: `memory_hierarchy`（MemoryItem 相关）+ 抽取入库处
- 做法: 入库前按 key 相等 或 向量相似度 ≥0.9 合并，importance 累加、保留最新 value；
  用 HippocampalReplay 语义做离线回放合并（先落盘再合并）。
- 验收: 同一事实重复陈述 N 次，库中仅 1 条且 importance 递增；检索不返回重复项。

### M3 遗忘曲线排序注入（long-term 记忆不丢）
- 位置: `build_system_prompt` 注入排序 + `EbbinghausForgetting`
- 做法: 注入/检索排序 = importance × retention（retention 来自遗忘曲线，last_reviewed
  随命中更新）；配合 M2，长期记忆随复习频率自然分层（WORKING/LONG_TERM/ARCHIVAL）。
- 验收: 高频事实 retention 高、持续可注入；低频事实降级到 ARCHIVAL 不占 prompt。

## 组合效果（指数级定义）
- 单轮 token 成本 = 固定缓存前缀 + O(k) 检索注入 + 压缩后工具帧 → 与历史长度、记忆总量解耦。
- 记忆容量 = 磁盘容量级（几十万条），注入恒为 top-k。

## 约束
- 17 脑区架构与现有 API 契约不变；`build_system_prompt` 为 CLI/UI 共用，改动需两端一致。
- 每个任务先补测试再改（仓库惯例），全量 `tests/` 必须 0 failed。
- 三平台路径（CrossPlatformStorage）沿用现有实现，不得引入硬编码 `~/.meshctx`。
- 实施完成后发回执：commit 列表 + 各任务验收数据 + 待审计点。002 负责最终审计。
