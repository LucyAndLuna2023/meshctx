# Terminal-Bench 2.0 Harness

Terminal-Bench 2.0 基准测试框架，用于评估 meshctx agent 在终端命令执行任务上的表现。

## 2026 规范对齐

- **评分维度**: exit_code (15%), stdout_match (50%), timeout (10%), stderr_check (10%), efficiency (15%)
- **通过标准**: 总分 ≥ 80% 且所有 success_criteria 满足
- **总分**: passed / total tasks

## 目录结构

```
terminal_bench/
├── scorer.py              # 评分逻辑（五维度加权评分）
├── harness.py             # 测试框架主入口
├── adapters/
│   └── meshctx_adapter.py # Terminal-Bench 专用适配器（命令执行 + 输出验证）
├── sample_tasks.json      # 示例任务（5个任务，涵盖文件/文本/系统/网络/进程）
└── README.md              # 本文件
```

## 快速开始

### 1. 使用示例任务运行

```bash
cd benchmarks/terminal_bench

# 运行所有示例任务
python3 harness.py -t sample_tasks.json

# 仅运行指定任务
python3 harness.py -t sample_tasks.json --task termbench__file_ops__001

# 指定模型和参数
python3 harness.py -t sample_tasks.json -m deepseek-v4-pro --timeout 180 --max-steps 15
```

### 2. 使用自定义任务

```bash
python3 harness.py -t my_tasks.json -o ./my_results
```

### 3. 仅评分

```bash
python3 scorer.py sample_tasks.json predictions.json results.json
```

## 任务格式

```json
{
  "task_id": "唯一标识",
  "category": "任务类别（文件操作/文本处理/系统信息/网络操作/进程管理）",
  "difficulty": "难度（easy/medium/hard）",
  "prompt": "任务描述",
  "setup_commands": ["前置命令列表"],
  "expected_output": "期望输出（为空时只检查 success_criteria）",
  "expected_exit_code": 0,
  "success_criteria": ["正则表达式列表，全部匹配则通过"]
}
```

## 评分逻辑

### 五维度加权评分

| 维度 | 权重 | 说明 |
|------|------|------|
| exit_code | 15% | 退出码是否与预期一致 |
| stdout_match | 50% | 输出内容与期望输出的模糊匹配度 |
| timeout | 10% | 是否在时限内完成 |
| stderr_check | 10% | 是否有意外错误输出 |
| efficiency | 15% | 执行效率（基于耗时） |

### stdout_match 算法

1. 标准化（去空白、转小写）
2. 完全匹配 → 100%
3. 子串匹配 → 90%
4. Jaccard 标记重合度 → 重合比例

### efficiency 阶梯评分

| 耗时 | 分数 |
|------|------|
| ≤ 5s | 100% |
| ≤ 15s | 90% |
| ≤ 30s | 75% |
| ≤ 60s | 60% |
| ≤ 120s | 40% |
| > 120s | 20% |

## 输出格式

```json
{
  "benchmark": "Terminal-Bench 2.0",
  "version": "2026",
  "summary": {
    "total_tasks": 5,
    "passed": 4,
    "failed": 1,
    "pass_rate": 0.80,
    "avg_total_score": 0.87
  },
  "dimensions": {
    "exit_code": {"avg_score": 0.95, "weight": 0.15},
    "stdout_match": {"avg_score": 0.82, "weight": 0.50},
    ...
  },
  "per_task": [...]
}
```

## 适配器说明

`TerminalBenchAdapter` 继承自通用 `MeshctxAdapter`，额外提供:

- `execute_commands(cmds)` — 批量执行 shell 命令
- `execute_single(cmd)` — 执行单条命令
- `run_task(task)` — 一键完成: setup → agent → extract → execute → verify

## 依赖

- Python 3.10+
- meshctx 现有依赖（无额外 pip 安装）
- 标准 Linux 命令行工具（awk, sort, curl 等）
