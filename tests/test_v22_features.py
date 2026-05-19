"""
v2.22 新增功能测试 — 自愈2.0 + 多Agent2.0
"""
import pytest
import requests
import time

BASE = "http://127.0.0.1:3001"


class TestAutoHealerV2:
    """自愈2.0 测试"""

    def test_healer_dashboard(self):
        """仪表板返回完整数据"""
        r = requests.get(f"{BASE}/api/healer/dashboard")
        assert r.status_code == 200
        d = r.json()
        assert "status" in d
        assert "color" in d
        assert "health_score" in d
        assert "predictions" in d
        assert "heals_performed" in d
        assert "uptime_human" in d
        print(f"  ✓ health_score={d['health_score']}, color={d['color']}, status={d['status']}")

    def test_healer_status(self):
        """状态端点"""
        r = requests.get(f"{BASE}/api/healer/status")
        assert r.status_code in (200, 503)  # 503=healer not started (ok)
        d = r.json()
        assert "status" in d or "error" in d
        print(f"  ✓ healer status: {d}")

    def test_healer_history(self):
        """历史记录"""
        r = requests.get(f"{BASE}/api/healer/history?limit=5")
        assert r.status_code in (200, 503)
        print(f"  ✓ history: {r.status_code}")

    def test_healer_manual_check(self):
        """手动检测"""
        r = requests.post(f"{BASE}/api/healer/run")
        assert r.status_code in (200, 503)
        if r.status_code == 200:
            d = r.json()
            assert "healthy" in d
            print(f"  ✓ manual check: healthy={d['healthy']}")


class TestMultiAgentV2:
    """多Agent2.0 测试"""

    def test_multi_agent_status(self):
        """多Agent状态"""
        r = requests.get(f"{BASE}/api/multi-agent/status")
        assert r.status_code == 200
        d = r.json()
        assert "manager" in d
        assert "executor" in d
        print(f"  ✓ agents={d['manager']['agent_count']}")

    def test_create_team(self):
        """创建Agent团队"""
        r = requests.post(f"{BASE}/api/multi-agent/create-team")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "created"
        assert len(d["agents"]) == 5
        assert "searcher" in d["agents"]
        assert "analyst" in d["agents"]
        assert "coder" in d["agents"]
        print(f"  ✓ team created: {list(d['agents'].keys())}")

    def test_decompose_research(self):
        """分解研究任务"""
        r = requests.post(f"{BASE}/api/multi-agent/decompose", json={
            "type": "research",
            "description": "AI Agent market 2026",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["total_subtasks"] >= 3
        assert len(d["subtasks"]) >= 3
        print(f"  ✓ decomposed into {d['total_subtasks']} subtasks")

    def test_decompose_code(self):
        """分解代码任务"""
        r = requests.post(f"{BASE}/api/multi-agent/decompose", json={
            "type": "code",
            "description": "Implement login page",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["total_subtasks"] >= 3
        print(f"  ✓ code task → {d['total_subtasks']} subtasks")

    def test_decompose_analysis(self):
        """分解分析任务"""
        r = requests.post(f"{BASE}/api/multi-agent/decompose", json={
            "type": "analysis",
            "description": "Analyze Q1 revenue",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["total_subtasks"] >= 3
        print(f"  ✓ analysis → {d['total_subtasks']} subtasks")

    def test_execution_plan(self):
        """执行计划"""
        r = requests.post(f"{BASE}/api/multi-agent/plan", json={
            "type": "report",
            "description": "Monthly performance report",
        })
        assert r.status_code == 200
        d = r.json()
        assert "task" in d
        assert "subtasks" in d
        assert "parallelism" in d
        print(f"  ✓ plan: {d['parallelism']}")

    def test_execute_task(self):
        """执行分解任务"""
        r = requests.post(f"{BASE}/api/multi-agent/execute", json={
            "type": "analysis",
            "description": "Quick check on system health",
        })
        assert r.status_code == 200
        d = r.json()
        assert "subtasks_total" in d
        assert "results" in d
        assert "merged" in d
        assert d["subtasks_completed"] > 0
        print(f"  ✓ executed: {d['subtasks_completed']}/{d['subtasks_total']} completed")


class TestV22Integration:
    """v2.22 集成测试"""

    def test_version_bump(self):
        """版本号正确"""
        r = requests.get(f"{BASE}/api/version")
        assert r.status_code == 200
        d = r.json()
        assert d["version"].startswith("2."), f"Version not 2.x: {d['version']}"
        assert d["models"] == 123
        assert d["providers"] == 37
        print(f"  ✓ v{d['version']} models={d['models']} providers={d['providers']}")

    def test_all_critical_endpoints(self):
        """所有关键端点可达"""
        endpoints = [
            "/api/version", "/health", "/api/health",
            "/api/healer/dashboard", "/api/healer/status",
            "/api/multi-agent/status",
        ]
        for ep in endpoints:
            r = requests.get(f"{BASE}{ep}", timeout=5)
            assert r.status_code in (200, 503), f"{ep} → {r.status_code}"
        print(f"  ✓ {len(endpoints)} critical endpoints OK")

    def test_context_build_get(self):
        """context/build GET返回文档"""
        r = requests.get(f"{BASE}/context/build")
        assert r.status_code == 200
        d = r.json()
        assert d["method"] == "POST"
        print(f"  ✓ context/build docs OK")

    def test_file_list(self):
        """file/list 默认路径"""
        r = requests.get(f"{BASE}/api/file/list", timeout=5)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d
        print(f"  ✓ file/list: {len(d['items'])} items in {d['path']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
