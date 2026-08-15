"""
test_v49_agent_crew_features.py
===============================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

对标 hermes-studio / penguin-harness 的新特性测试：

  * agent_crew_templates  —— 7 Crew + 4 Conductor 模板 + 克隆 + 成本估算
  * agent_writing_studio  —— 智能体库写作助手（角色模板 + 起草 + 克隆）
  * agent_crew_cost_tracker —— per-crew 成本追踪
  * agent_tuning_skills   —— Agent Tuning 技能包 + 自我进化闭环
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.agent_crew_templates import (
    CREW_TEMPLATES,
    CONDUCTOR_TEMPLATES,
    CrewTemplateEngine,
    get_crew_engine,
)
from src.core.agent_writing_studio import (
    ROLE_WRITING_TEMPLATES,
    AgentWritingStudio,
    get_writing_studio,
)
from src.core.agent_crew_cost_tracker import CrewCostTracker
from src.core.agent_tuning_skills import AgentTuningSkillPack


# ══════════════════════════════════════════════════════════════════
# agent_crew_templates
# ══════════════════════════════════════════════════════════════════

class TestCrewTemplates:
    @pytest.fixture(autouse=True)
    def _isolate_storage(self, tmp_path, monkeypatch):
        """每个测试用独立存储，避免 clone 落盘污染默认 ~/.meshctx。"""
        monkeypatch.setenv("MESHCTX_HOME", str(tmp_path))

    def test_builtin_template_counts(self):
        assert len(CREW_TEMPLATES) == 7
        assert len(CONDUCTOR_TEMPLATES) == 4

    def test_engine_loads_all_11(self):
        e = CrewTemplateEngine()
        assert len(e.list_templates()) == 11
        assert len(e.list_templates("crew")) == 7
        assert len(e.list_templates("conductor")) == 4

    def test_instantiate_renders_goal(self):
        e = CrewTemplateEngine()
        plan = e.instantiate("build", "做一个TODO应用")
        assert len(plan) == 3
        assert plan[0]["agent"] == "architect"
        assert "做一个TODO应用" in plan[0]["instruction"]

    def test_run_dispatches_all_steps(self):
        e = CrewTemplateEngine()
        result = e.run("review", "审查登录模块")
        assert len(result["dispatches"]) == 2
        assert result["estimated_tokens"] > 0

    def test_clone(self):
        e = CrewTemplateEngine()
        cloned = e.clone("research", "research_custom", persist=False)
        assert cloned.name == "research_custom"
        assert cloned.builtin is False
        assert len(cloned.steps) == len(CREW_TEMPLATES["research"].steps)

    def test_clone_unknown_raises(self):
        e = CrewTemplateEngine()
        with pytest.raises(KeyError):
            e.clone("nope", "x")

    def test_clone_duplicate_raises(self):
        e = CrewTemplateEngine()
        e.clone("build", "dup", persist=False)
        with pytest.raises(ValueError):
            e.clone("build", "dup", persist=False)

    def test_estimate_cost_shape(self):
        e = CrewTemplateEngine()
        est = e.estimate_cost("conductor_deploy")
        assert est["steps"] == 4
        assert est["est_tokens"] == 4800
        assert est["est_cost_usd_low"] < est["est_cost_usd_high"]

    def test_custom_template_persist(self, tmp_path):
        e = CrewTemplateEngine(storage_dir=str(tmp_path))
        e.clone("support", "support_v2")  # persist=True 落盘
        e2 = CrewTemplateEngine(storage_dir=str(tmp_path))
        assert e2.get_template("support_v2") is not None
        assert e2.get_template("support_v2").builtin is False


# ══════════════════════════════════════════════════════════════════
# agent_writing_studio
# ══════════════════════════════════════════════════════════════════

class TestWritingStudio:
    def test_role_templates_exist(self):
        assert set(ROLE_WRITING_TEMPLATES) == {
            "coder", "reviewer", "architect", "tester",
            "researcher", "devops", "general",
        }

    def test_draft_prompt_renders(self):
        s = AgentWritingStudio()
        d = s.draft_prompt("coder", "支付系统", "带测试的代码")
        assert "支付系统" in d.prompt
        assert "带测试的代码" in d.prompt

    def test_draft_unknown_role_raises(self):
        s = AgentWritingStudio()
        with pytest.raises(KeyError):
            s.draft_prompt("nonexistent")

    def test_create_agent(self):
        s = AgentWritingStudio()
        d = s.draft_prompt("researcher", "竞品分析")
        a = s.create_agent("分析员_测试", "researcher", d.prompt, temperature=0.1)
        assert a.name == "分析员_测试"
        assert a.system_prompt == d.prompt
        s.delete_agent("分析员_测试")

    def test_create_duplicate_raises(self):
        s = AgentWritingStudio()
        with pytest.raises(ValueError):
            s.create_agent("coder", "custom", "重复")  # coder 已内置

    def test_clone_agent(self):
        s = AgentWritingStudio()
        c = s.clone_agent("coder", "coder_克隆")
        assert c.name == "coder_克隆"
        assert c.system_prompt == s.tm.get_agent("coder").system_prompt
        s.delete_agent("coder_克隆")

    def test_edit_prompt(self):
        s = AgentWritingStudio()
        s.create_agent("编辑目标", "custom", "旧提示词")
        s.edit_prompt("编辑目标", "新提示词")
        assert s.tm.get_agent("编辑目标").system_prompt == "新提示词"
        s.delete_agent("编辑目标")

    def test_builtin_not_deletable(self):
        s = AgentWritingStudio()
        assert s.delete_agent("coder") is False

    def test_import_library(self):
        s = AgentWritingStudio()
        n = s.import_library([
            {"name": "导入A", "role": "coder", "system_prompt": "pA"},
            {"name": "导入B", "role": "researcher", "system_prompt": "pB"},
            {"name": "coder"},  # 内置同名，不覆盖
        ])
        assert n == 2
        assert s.tm.get_agent("导入A").system_prompt == "pA"
        s.delete_agent("导入A")
        s.delete_agent("导入B")


# ══════════════════════════════════════════════════════════════════
# agent_crew_cost_tracker
# ══════════════════════════════════════════════════════════════════

class TestCrewCostTracker:
    def test_estimate_run(self, tmp_path):
        t = CrewCostTracker(storage_dir=str(tmp_path / "c.json"))
        est = t.estimate_run("build", "目标")
        assert est["steps"] == 3
        assert est["est_tokens"] > 0
        assert est["model_route"] in ("flash", "pro", "mix")

    def test_track_and_report(self, tmp_path):
        t = CrewCostTracker(storage_dir=str(tmp_path / "c.json"))
        t.track_run("build", "做TODO应用")
        t.track_run("build", "重构认证")
        rep = t.get_crew_report("build")
        assert rep["runs"] == 2
        assert rep["total_tokens"] > 0

    def test_all_reports_sorted_by_cost(self, tmp_path):
        t = CrewCostTracker(storage_dir=str(tmp_path / "c.json"))
        t.track_run("research", "调研")     # 2 steps
        t.track_run("conductor_deploy", "部署")  # 4 steps
        reports = t.get_all_reports()
        assert reports[0]["template"] == "conductor_deploy"

    def test_reset(self, tmp_path):
        t = CrewCostTracker(storage_dir=str(tmp_path / "c.json"))
        t.track_run("build", "x")
        t.reset("build")
        assert t.get_crew_report("build")["runs"] == 0

    def test_unknown_template_raises(self, tmp_path):
        t = CrewCostTracker(storage_dir=str(tmp_path / "c.json"))
        with pytest.raises(KeyError):
            t.estimate_run("不存在")


# ══════════════════════════════════════════════════════════════════
# agent_tuning_skills
# ══════════════════════════════════════════════════════════════════

class TestTuningSkills:
    def test_list_skills(self):
        p = AgentTuningSkillPack()
        skills = [s["skill"] for s in p.list_skills()]
        assert skills == ["agent-creation", "benchmark-design",
                          "agent-evaluation", "agent-optimization"]

    def test_skill_agent_creation(self):
        p = AgentTuningSkillPack()
        r = p.skill_agent_creation("风控专家", "coder", "支付风控")
        assert r["status"] == "created"
        assert "支付风控" in r["prompt"]
        p.studio.delete_agent("风控专家")

    def test_skill_benchmark_design(self):
        p = AgentTuningSkillPack()
        r = p.skill_benchmark_design("风控评测", "风控",
                                     tasks=["反欺诈"], metrics=["precision"])
        assert r["spec"]["name"] == "风控评测"
        assert r["spec"]["metrics"] == ["precision"]

    def test_skill_agent_evaluation(self):
        p = AgentTuningSkillPack()
        r = p.skill_agent_evaluation()
        assert isinstance(r["suites"], list)
        assert 0.0 <= r["avg_score"] <= 1.0

    def test_skill_agent_optimization(self):
        p = AgentTuningSkillPack()
        r = p.skill_agent_optimization(
            "x", ["短", "中等长度的变体", "非常详细具体的中文提示词变体"],
            metric="accuracy")
        assert r["winner"] == "v2"
        assert r["variants_tested"] == 3

    def test_optimization_empty_variants_raises(self):
        p = AgentTuningSkillPack()
        with pytest.raises(ValueError):
            p.skill_agent_optimization("x", [])

    def test_tuning_loop_improves(self):
        p = AgentTuningSkillPack()
        r = p.run_tuning_loop("agent_x", "coder", "支付风控",
                              rounds=3, base_score=0.6)
        assert r["rounds"] == 3
        assert r["final_score"] > 0.6
        assert r["improvement"] > 0
        assert len(r["history"]) == 3


class TestWebCrewsUI:
    """对标 hermes-studio / penguin-harness 的 Web UI 层（十语言 + 页面渲染）。"""

    def test_i18n_ten_languages_have_new_keys(self):
        from src.i18n import TRANSLATIONS
        for key in ("crew_title", "agent_library_title", "tuning_title",
                    "crew_dag_title", "tuning_loop_title"):
            for lang in ("zh", "en", "ja", "ko", "fr", "de", "es", "it", "ar", "ru"):
                assert key in TRANSLATIONS[lang], f"{lang} 缺 {key}"
                assert TRANSLATIONS[lang][key], f"{lang}.{key} 为空"

    def test_new_templates_render(self):
        import src.web_crews  # noqa: F401  触发模板注册到 web_ui._TEMPLATES
        from src.web_ui import _render
        r1 = _render("crews.html", {
            "crew": [{"name": "research", "steps": [{"agent": "a", "instruction": "i"}],
                      "est_low": 0.01, "est_high": 0.05}],
            "conductor": [], "msg": None, "err": None}, None)
        r2 = _render("agents_library.html",
                     {"builtin": [], "custom": [], "roles": ["coder"]}, None)
        r3 = _render("tuning.html",
                     {"skills": [], "roles": ["coder"], "result": None}, None)
        r4 = _render("crews_dag.html",
                     {"dag": [{"agent": "a", "instruction": "i"}], "feed": []}, None)
        for name, resp in (("crews", r1), ("agents", r2), ("tuning", r3), ("dag", r4)):
            assert resp.status_code == 200, name
            assert len(resp.body) > 1000, name

    def test_web_crews_router_mounted(self):
        import src.main as m

        def collect(routes):
            out = []
            for r in routes:
                if hasattr(r, "path"):
                    out.append(r.path)
                elif hasattr(r, "original_router"):
                    out.extend(collect(r.original_router.routes))
                elif hasattr(r, "routes"):
                    out.extend(collect(r.routes))
            return out
        paths = set(collect(m.app.routes))
        for p in ("/ui/crews", "/ui/crews/dag", "/ui/agents", "/ui/tuning"):
            assert p in paths, f"缺少路由 {p}"

    def test_writing_studio_list_builtin_custom(self):
        from src.core.agent_writing_studio import AgentWritingStudio, BUILTIN_AGENTS
        s = AgentWritingStudio()
        builtin = s.list_builtin()
        assert len(builtin) == len(BUILTIN_AGENTS)
        assert all(a["name"] in BUILTIN_AGENTS for a in builtin)
        # 自定义 agent 不应出现在 builtin 列表
        s.create_agent("__tui_custom__", "general", "test prompt")
        assert all(a["name"] != "__tui_custom__" for a in s.list_builtin())
        assert any(a["name"] == "__tui_custom__" for a in s.list_custom())
        s.delete_agent("__tui_custom__")

    def test_cost_tracker_get_feed(self):
        from src.core.agent_crew_cost_tracker import CrewCostTracker
        t = CrewCostTracker(storage_dir="/tmp/crew_feed_test.json")
        t.reset()
        t.track_run("build", "feed 测试任务", tokens=1200, cost_usd=0.018)
        feed = t.get_feed()
        assert feed and feed[0]["agent"] == "build"
        assert feed[0]["tokens"] == 1200
        t.reset()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
