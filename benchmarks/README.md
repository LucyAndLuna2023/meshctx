# meshctx benchmarks（评测公信力 harness, WP2 / MCTX-PLAN-2026-0903 P0-2）

让 meshctx 成绩进入**官方口径**（SWE-bench Verified / GAIA / LongMemEval_S），
替代内部启发式对外表述。本目录独立于主程序（D5），不进日常 pytest/安装器。

## 结构

```
benchmarks/
  meshctx_benchmarks/core.py      # 纯函数共享核心: report schema / 实例解析 / EM 打分
  swebench_runner.py              # SWE-bench Verified 编排 (docker 镜像门控)
  gaia_longmem_runner.py          # GAIA 提交构造 + LongMem 问答打分
  README.md                       # 本文件
tests/test_benchmarks_core.py     # 纯函数单测 (无 docker/数据集)
```

## 口径纪律（报告第八章"口径警示"对策）

- 一律分表呈现：`self_run`（本地复现）/ `official_submission`（官方榜）/ `reference`（厂商引用）。
- 分数与厂商自报（如 OMEGA 95.4%）**不直接排名**；不同基准不可互换。
- `core.validate_report` 强制 results.mode 三选一，防混排。

## 运行

```bash
# 纯函数测试 (CI 常跑)
python -m pytest tests/test_benchmarks_core.py

# SWE-bench: dry-run 出实例汇总/计划 (无需 docker)
python benchmarks/swebench_runner.py --jsonl instances.jsonl --dry-run

# SWE-bench: 真实运行 (需 docker + 官方镜像, 凭据 env)
MESHCTX_SWE_IMAGE=<swebench-eval-image> python benchmarks/swebench_runner.py --jsonl ... --out report.json

# LongMem 风格问答打分 (本地可跑)
python benchmarks/gaia_longmem_runner.py longmem --questions q.jsonl --predictions p.jsonl

# GAIA 提交构造 (官方协议发布后对齐字段)
python benchmarks/gaia_longmem_runner.py gaia-submission --answers ans.json
```

## 凭据/CI 门控

- 官方榜提交账号与凭据不进仓库（同 provider_config 处理），由 benchmark-nightly
  workflow 在受控 runner 触发；分数归属运营资产。
- 本目录代码不引入运行时依赖（纯 stdlib）；swebench 镜像仅在真实运行步使用。

## 成绩页

`docs/benchmarks/`（10 语言 i18n 后补）—— 仅发布经 `validate_report` 且注明口径的成绩。
