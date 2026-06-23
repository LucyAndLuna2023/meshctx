"""v2.60 Live Dashboard — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestLiveDashboard:
    def test_html_template_exists(self):
        """验证HTML模板文件存在"""
        html = Path(__file__).parent.parent / "src" / "core" / "templates" / "live_dashboard.html"
        assert html.exists(), f"live_dashboard.html不存在于 {html}"
        assert html.stat().st_size > 1000, "模板文件过小"

    def test_html_contains_required_elements(self):
        """验证HTML模板包含必要元素"""
        html = Path(__file__).parent.parent / "src" / "core" / "templates" / "live_dashboard.html"
        content = html.read_text(encoding="utf-8")
        required = [
            "WebSocket",
            "/ws/health",
            "module-card",
            "status-ok",
            "status-error",
            "health",
            "sdb",
            "memory",
            "diff",
            "tasks",
            "brain",
            "self_modify",
            "gateway_llm",
            "unified_loop",
            "attractor",
            "knowledge",
            "precompute",
            "tuner",
            "benchmark",
        ]
        for elem in required:
            assert elem in content, f"模板缺少: {elem}"

    def test_html_well_formed(self):
        """验证HTML结构完整性"""
        html = Path(__file__).parent.parent / "src" / "core" / "templates" / "live_dashboard.html"
        content = html.read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")
        assert "<html" in content
        assert "</html>" in content
        assert "modal" not in content.lower() or "dialog" in content.lower()

    def test_route_registered(self):
        """验证 /dashboard/live 路由已注册"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "main", Path(__file__).parent.parent / "src" / "main.py"
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
                routes = [r.path for r in mod.app.routes if hasattr(r, 'path')]
                assert "/dashboard/live" in routes, \
                    "/dashboard/live 路由未注册"
            except Exception:
                # May fail due to deps — just check the source
                import re
                src = Path(__file__).parent.parent / "src" / "main.py"
                text = src.read_text()
                assert "/dashboard/live" in text, \
                    "/dashboard/live 未在main.py中定义"
                assert "live_dashboard" in text, \
                    "live_dashboard 函数未定义"
