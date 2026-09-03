"""WP2 (MCTX-PLAN-2026-0903 P0-2) benchmarks 共享核心纯函数测试。

无 docker/数据集依赖: report schema / SWE 实例解析汇总 / EM 打分口径。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))

from meshctx_benchmarks.core import (em_score, exact_match, f2p_p2p_sets,  # noqa: E402
                                     load_swe_instances, normalize_answer,
                                     summarize_instances, validate_report,
                                     write_report)


class TestNormalizeAndEM:
    def test_normalize(self):
        assert normalize_answer("  Hello,   World!  ") == "hello, world!"
        assert normalize_answer("") == ""

    def test_exact_strict(self):
        assert exact_match("Paris", "paris")
        assert exact_match("2026-09-03", "2026-09-03")
        assert not exact_match("paris france", "paris")

    def test_exact_loose_candidates(self):
        assert exact_match("42", "42 | 43")
        assert exact_match("42", "40|42")
        assert not exact_match("7", "40|42")
        # loose 包含: 候选长度>2 才做包含匹配 (防数字/短串误包含)
        assert exact_match("答案是 paris france", "paris france | london", loose=True)
        assert not exact_match("答案是 paris", "paris france | london", loose=True)

    def test_em_score_batch(self):
        scored = em_score([("a", "a"), ("b", "c"), ("", "d")])
        assert scored["total"] == 3
        assert scored["correct"] == 1
        assert scored["em"] == pytest.approx(1 / 3, abs=0.001)
        assert scored["misses"] == [1, 2]


class TestReport:
    def test_validate_ok(self):
        rep = {"schema": "1.0", "benchmark": "longmem_s", "date": "t",
               "head": "h", "config": {}, "results": {"mode": "self_run",
               "metric": "em", "em": 0.5, "total": 10}}
        assert validate_report(rep) == []

    def test_validate_bad_mode(self):
        rep = {"schema": "1.0", "benchmark": "x", "date": "t", "head": "h",
               "config": {}, "results": {"mode": "mixed_self_official",
                                         "metric": "em"}}
        assert validate_report(rep)  # 口径纪律: 不允许混排 mode

    def test_write_report_roundtrip(self, tmp_path):
        rep = {"benchmark": "swebench_verified", "head": "abc",
               "config": {}, "results": {"mode": "self_run", "metric": "resolved",
                                         "resolved": 0.0}}
        p = write_report(rep, tmp_path / "r.json")
        assert json.loads(p.read_text(encoding="utf-8"))["benchmark"] == "swebench_verified"


class TestSweInstances:
    def _jsonl(self, tmp_path):
        lines = [
            {"instance_id": "repo__proj-1", "base_commit": "abc123",
             "patch": "--- a/x\n+++ b/x\n@@\n+fix", "FAIL_TO_PASS": ["t1"],
             "PASS_TO_PASS": ["t0"]},
            {"instance_id": "repo__proj-2", "base_commit": "def456",
             "patch": "--- a/y\n+++ b/y\n@@\n+fix2", "FAIL_TO_PASS": "t2,t3",
             "PASS_TO_PASS": ["t0", "t4"]},
        ]
        p = tmp_path / "inst.jsonl"
        p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
        return p

    def test_load_required_keys(self, tmp_path):
        p = self._jsonl(tmp_path)
        insts = load_swe_instances(p)
        assert len(insts) == 2
        with pytest.raises(ValueError):
            bad = tmp_path / "bad.jsonl"
            bad.write_text(json.dumps({"instance_id": "x"}) + "\n", encoding="utf-8")
            load_swe_instances(bad)

    def test_f2p_p2p_normalization(self):
        inst = {"FAIL_TO_PASS": "t1,t2", "PASS_TO_PASS": ["t0"]}
        f2p, p2p = f2p_p2p_sets(inst)
        assert f2p == {"t1", "t2"} and p2p == {"t0"}
        f2p2, _ = f2p_p2p_sets({"fail_to_pass": ["t9"]})
        assert f2p2 == {"t9"}

    def test_summary(self, tmp_path):
        insts = load_swe_instances(self._jsonl(tmp_path))
        s = summarize_instances(insts)
        assert s["instances"] == 2
        assert s["f2p_tests"] == 3          # 1 + "t2,t3"
        assert s["p2p_tests"] == 3
        assert s["patched"] == 2


    def test_metric_must_be_real(self):
        """P3-B (004meshctx): metric=resolved 无实算值 + 非 dry → 不合规 (禁占位假跑分)。"""
        rep = {"schema": "1.0", "benchmark": "swebench_verified", "date": "t",
               "head": "h", "config": {},
               "results": {"mode": "self_run", "metric": "resolved",
                           "instances": [{"status": "ran"}]}}
        assert validate_report(rep)          # 占位 status=ran 无 resolved → 拦
        # dry-run 计划 (mode_hint) 豁免
        rep["mode_hint"] = "dry-run"
        assert validate_report(rep) == []
