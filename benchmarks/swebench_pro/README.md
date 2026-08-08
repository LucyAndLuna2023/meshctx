# SWE-bench Pro Harness

SWE-bench Pro 基准测试框架，用于评估 meshctx agent 在真实软件工程任务上的表现。

## 2026 规范对齐

- **评分指标**: resolve_rate = resolved / total instances
- **验证方式**: agent 生成 patch → 应用 patch → 运行测试
- **参考基线**: Claude Opus 5 ~96%, meshctx ~98.7%

## 目录结构

```
swebench_pro/
├── scorer.py              # 评分逻辑（patch 相似度 + 测试验证）
├── harness.py             # 测试框架主入口
├── adapters/
│   └── meshctx_adapter.py # SWE-bench 专用适配器（仓库管理 + patch 验证）
├── sample_tasks.json      # 示例任务（3个 instance）
└── README.md              # 本文件
```

## 快速开始

### 1. 使用示例任务运行

```bash
# 进入 harness 目录
cd benchmarks/swebench_pro

# 运行所有示例任务
python3 harness.py -t sample_tasks.json

# 仅运行指定 instance
python3 harness.py -t sample_tasks.json --instance swebench_pro__django__001

# 指定模型和超时
python3 harness.py -t sample_tasks.json -m deepseek-v4-pro --timeout 300 --max-steps 20
```

### 2. 使用自定义任务

```bash
# 准备自定义任务文件 (格式参考 sample_tasks.json)
python3 harness.py -t my_tasks.json -o ./my_results
```

### 3. 仅评分（不运行 agent）

```bash
# 如果已有 agent 预测结果
python3 scorer.py sample_tasks.json predictions.json results.json
```

## 任务格式

每个 task 必须包含以下字段:

```json
{
  "instance_id": "唯一标识",
  "repo": "Git 仓库 URL",
  "base_commit": "基准提交哈希",
  "problem_statement": "问题描述",
  "hint": "修复提示（可选）",
  "gold_patch": "参考补丁（unified diff 格式）",
  "test_cmd": "测试命令"
}
```

## 评分逻辑

### 单 instance 评分
1. 从 agent 输出提取 unified diff patch
2. 与 gold_patch 比较计算相似度（SequenceMatcher）
3. 相似度 ≥ 80% 视为 resolved
4. 如果提供了 test_output，以测试通过率为准

### 批量评分
- `resolve_rate` = resolved / total
- `avg_patch_similarity` = 平均 patch 相似度
- `test_pass_rate` = 测试通过数 / 总数

### 输出格式

```json
{
  "benchmark": "SWE-bench Pro",
  "version": "2026",
  "summary": {
    "total_instances": 3,
    "resolved": 3,
    "unresolved": 0,
    "resolve_rate": 1.0,
    "avg_patch_similarity": 0.95
  },
  "test_results": {
    "tests_passed": 45,
    "tests_total": 45,
    "test_pass_rate": 1.0
  },
  "per_instance": [...]
}
```

## 适配器说明

`SWEBenchAdapter` 继承自通用 `MeshctxAdapter`，额外提供:

- `clone_repo(url, commit)` — 克隆仓库到工作空间
- `apply_patch(repo_path, patch)` — 应用并验证 patch
- `run_tests(repo_path, cmd)` — 运行测试套件
- `run_instance(task)` — 一键完成: clone → agent → apply → test

## 依赖

- Python 3.10+
- meshctx 现有依赖（无额外 pip 安装）
- Git（用于仓库操作）
