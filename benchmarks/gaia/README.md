# GAIA Benchmark Harness

GAIA (General AI Assistant) 基准测试框架，用于评估 meshctx agent 在通用推理和信息检索任务上的表现。

## 2026 规范对齐

- **三级难度**: L1 基础信息检索、L2 多步推理、L3 复杂推理
- **评分方式**: exact match / normalized match / F1
- **2026 leaderboard 参考**: Manus AI 86.5% L1
- **答案类型**: text / number / list / json

## 目录结构

```
gaia/
├── scorer.py              # 评分逻辑（三级评分 + F1）
├── harness.py             # 测试框架主入口
├── adapters/
│   └── meshctx_adapter.py # GAIA 专用适配器（答案提取 + 分级策略）
├── sample_tasks.json      # 示例任务（8个，覆盖 L1/L2/L3）
└── README.md              # 本文件
```

## 快速开始

### 1. 使用示例任务运行

```bash
cd benchmarks/gaia

# 运行所有任务
python3 harness.py -t sample_tasks.json

# 仅运行 Level 1 任务
python3 harness.py -t sample_tasks.json --level 1

# 仅运行 Level 2 和 3
python3 harness.py -t sample_tasks.json --level 2 3

# 仅运行指定任务
python3 harness.py -t sample_tasks.json --task gaia__l1__001 gaia__l2__001

# 指定模型
python3 harness.py -t sample_tasks.json -m deepseek-v4-pro --timeout 300
```

### 2. 使用自定义任务

```bash
python3 harness.py -t my_gaia_tasks.json -o ./my_results
```

### 3. 仅评分

```bash
python3 scorer.py sample_tasks.json predictions.json results.json
```

## 任务格式

```json
{
  "task_id": "唯一标识",
  "level": 1,
  "question": "问题描述",
  "ground_truth": "标准答案",
  "answer_type": "text",
  "file_name": "附件文件名（可选）",
  "hint": "提示信息（可选）"
}
```

## 评分逻辑

### 三级评分策略

| Level | 正确判定标准 | Agent 步数 | 超时 |
|-------|-------------|-----------|------|
| L1 基础 | exact match 或 normalized match | ≤10 | 180s |
| L2 中等 | exact match 或 F1 ≥ 0.80 | ≤25 | 300s |
| L3 高级 | exact match 或 F1 ≥ 0.80 | ≤40 | 600s |

### 答案标准化

- **text**: 转小写、去标点、统一引号、去前缀（"答案:" 等）
- **number**: 提取数值、保留合理精度、±0.01 容差
- **list**: 按逗号分项、排序、拼合
- **json**: 解析后按 key 排序重新序列化

### F1 计算

基于 token 级别的 precision 和 recall:

```
F1 = 2 × precision × recall / (precision + recall)
```

其中:
- precision = 预测 token 中出现在参考答案中的比例
- recall = 参考答案 token 中被预测覆盖的比例

### 答案提取

Agent 输出中按优先级匹配:
1. `答案: ...` / `Answer: ...`
2. `最终答案: ...` / `Final answer: ...`
3. `结果是: ...`
4. 最后一个非元信息行（回退策略）

## 输出格式

```json
{
  "benchmark": "GAIA",
  "version": "2026",
  "summary": {
    "total_tasks": 8,
    "correct": 6,
    "incorrect": 2,
    "accuracy": 0.75,
    "exact_match_rate": 0.50,
    "avg_f1": 0.82
  },
  "by_level": {
    "1": {"total": 3, "correct": 3, "accuracy": 1.0, "avg_f1": 0.95},
    "2": {"total": 3, "correct": 2, "accuracy": 0.67, "avg_f1": 0.78},
    "3": {"total": 2, "correct": 1, "accuracy": 0.50, "avg_f1": 0.70}
  },
  "per_task": [...]
}
```

## 适配器说明

`GAIAAdapter` 继承自通用 `MeshctxAdapter`，额外提供:

- `run_gaia_task(task)` — 根据 Level 自动调整策略运行任务
- `run_batch(tasks)` — 批量运行 GAIA 任务
- 智能答案提取（多策略回退）
- Level 感知的 prompt 模板

## 依赖

- Python 3.10+
- meshctx 现有依赖（无额外 pip 安装）
