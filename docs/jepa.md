# JEPA 世界模型 — 真实用途与验证

> 本文档回答：meshctx.com 宣传的「🧠 JEPA World Model」真实用途是什么、
> 开源版能验证到什么程度、验证数据在哪里。

## 1. 定位：不是"另一个生成模型"，而是记忆系统的非生成式预筛器

JEPA（Joint Embedding Predictive Architecture，LeCun 潜空间预测）在 MeshCtx 中
**不做文本生成**，而是承担记忆检索的"第一道闸门"：

```
query 到达
   │
   ▼
┌─────────────────────────────────────────┐
│ JEPA 潜空间预筛（不开 LLM，≈0 token）     │
│ char-trigram → 正交投影(QR) → 余弦排序    │
│ 从记忆库捞出 top-k 候选                    │
└─────────────────────────────────────────┘
   │ top-k（如 5 条）
   ▼
LLM 只对候选做精排/推理（token 只花在刀刃上）
```

**这就是"决策 token≈0"与"省 30~35% token"的真实机制**：不是玄学，
是"先筛后算"——用轻量潜空间相似度把 LLM 的候选池从全库缩到 top-k。

## 2. 实现（src/core/jepa_world_model.py，696 行）

| 组件 | 类 | 职责 |
|---|---|---|
| 编码器 | `JEPAEncoder` | 上下文/目标双塔编码 + EMA 目标网络更新 |
| 预测器 | `JEPAPredictor` | 潜空间预测 + **能量**（惊讶度）计算 + 训练步 |
| 世界模型 | `JEPAWorldModel` | perceive/predict/evaluate_outcome/健康度/分层预测 |
| 统一评分器 | `UnifiedScorer` | 能量+自由能评分、动作选择、决策置信度 |
| 非生成式路由 | `NonGenerativeRouter` | embed_state + 不开 LLM 的候选排序 |

开源版：QR 正交投影 + char-trigram 真实向量（基础模式）。
完整 VICReg 训练权重在 meshctx-core 私有核心（需授权）。

## 3. 验证（benchmarks/jepa/，LongMemEval oracle 数据）

### 3.1 大池检索（jepa_pool_validation.py，60 样本，30 条池 = 1 正 + 29 干扰）
- JEPA 非生成式：recall@1 **18.3%** / recall@5 **56.7%** / MRR **0.36**
- 随机基线：recall@1 3.3% → **JEPA 5.5× 于随机**
- 含义：LLM 调用量从 30 条降到 top-5（≈17%），仍保住 56.7% 召回

### 3.2 直接检索（jepa_memory_validation.py，100 样本）
- recall@1 / MRR = 100%（oracle 亦 100%，random 35%）
- ⚠️ 局限：该场景答案 session 与问题天然高相似，区分度弱，仅作机制冒烟

### 3.3 结果归档
- `benchmarks/jepa/results/jepa_pool_validation_results.json`
- `benchmarks/jepa/results/jepa_validation_results.json`

## 4. 诚实声明

- ✅ **已验证**：非生成式预筛在大池有效（5.5× 随机），"先筛后算"省 LLM token 的
  机制量化成立（top-5 保 56.7% 召回）。
- ⚠️ **未验证**：landing 宣传的"全系统 -30~35%"是产品愿景口径（含私有核心完整权重
  的收益），开源版仅验证记忆预筛环节，不构成全系统声称。
- 🚧 **JEPA Router**（jepa_router.py 121L）：基础路由已实现（任务编码/成本表），
  "预测式模型选择"为 STUB，待完整版。

## 5. 复现

```bash
python3 benchmarks/jepa/jepa_pool_validation.py        # 大池 30 条
python3 benchmarks/jepa/jepa_memory_validation.py 100  # 直接检索 100 样本
```
