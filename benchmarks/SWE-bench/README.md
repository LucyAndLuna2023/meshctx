# SWE-bench Benchmark for meshctx

## Setup
```bash
git clone https://github.com/princeton-nlp/SWE-bench.git
cd SWE-bench
pip install -e .
```

## Run meshctx on SWE-bench Lite
```bash
python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Lite \
  --predictions_path gold \
  --max_workers 4 \
  --run_id meshctx_v3.33 \
  --timeout 900
```

## Expected Results
- SWE-bench Lite: 300 instances
- Target: >30% resolve rate (baseline: Claude Code ~26%)
