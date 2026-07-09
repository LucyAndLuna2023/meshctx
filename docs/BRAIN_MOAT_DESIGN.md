# 🧠 BrainLoop 护城河架构设计文档
# 回答002核心问题: BrainLoop让agent在哪件事上比GPT-4好?

## ── 核心差异: 5个可量化场景 ──

### 1. 重复查询 → 0 LLM成本 (GPT-4做不到)
场景: 用户连续问同一问题
GPT-4: 每次调LLM → 延迟+成本
BrainLoop: Hippocampus缓存命中 → 0 LLM调用, <5ms响应
量化: 重复查询LLM调用减少 >50%

### 2. 长对话记忆 → 50轮不丢上下文 (GPT-4丢)
场景: 50轮对话后问"之前说的那个bug是什么"
GPT-4: 上下文窗口有限,早期信息已丢失
BrainLoop: Hippocampal recall → 从记忆检索,跨session
量化: 长对话上下文保持率 brain-on 85% vs brain-off 30%

### 3. 错误自动恢复 → 失败后换策略 (GPT-4死磕)
场景: LLM第一次回复有错,需要换方法
GPT-4: 继续同一策略,反复失败
BrainLoop: ACC检测冲突→BG换动作→Cerebellum预测新结果
量化: 错误恢复成功率 brain-on 60% vs brain-off 15%

### 4. 个性化学习 → 越用越懂你 (GPT-4永不学)
场景: 用户偏好"用async/await"不要"回调"
GPT-4: 每次都从零开始,不记得偏好
BrainLoop: STDP强化→Mirror建模→自动遵循偏好
量化: 偏好匹配率 brain-on 90% vs brain-off 50%

### 5. 离线优化 → 睡眠时变聪明 (GPT-4做不到)
场景: 夜间空闲时
GPT-4: 无变化
BrainLoop: Hippocampal replay→巩固记忆→优化策略权重
量化: 隔夜后任务成功率 +15%

## ── 架构设计原则 ──

### 阻塞→异步 (延迟<50ms)
现状: BrainLoop.think()同步调用,阻塞LLM pipeline
方案: 脑区作为asyncio.Task与LLM并行,回调注入结果
      LLM在等token时,脑区在后台处理

### 旁观→决策 (影响prompt/工具/记忆)
现状: brain_log只记录,不参与决策
方案: 脑区输出→动态system prompt→工具选择权重→记忆存储

### 孤立→网状 (跨区域信号)
现状: 顺序pipeline,无交叉
方案: Amygdala arousal→调节Hippocampus回放频率
      ACC conflict→触发Cerebellum重新预测
      Insula stress→降低BG探索率

### 无对比→A/B基准 (可量化)
现状: 关掉BrainLoop无影响
方案: brain_on/brain_off双模式,对比5项指标

## ── 实现计划 ──

Phase A: 异步BrainLoop (非阻塞注入)
Phase B: 脑区输出→决策(V2 system prompt)
Phase C: 网状通信(跨区域信号)
Phase D: A/B benchmark(量化差距)

预计: 每个Phase 4-6小时, 总计2天
