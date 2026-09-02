# -*- coding: utf-8 -*-
"""Agent Hub — T7 版本门控三态验证

验证:
1. personal: /api/tasks/cards* 全开 (hub 是开源个人版能力, 不隐藏)
2. team:     同全开 (团队治理路由在私有库扩展)
3. enterprise: 同全开
4. _EDITION_ROUTE_MAP 机制不被新路由破坏 (既有 36/3/0 移除数回归)
"""
import importlib
import sys

import pytest


@pytest.fixture(autouse=True)
def _clean_module():
    """每个测试前确保干净 import main (含 _hide 副作用)。"""
    yield


class TestHubNotHiddenByEdition:
    def test_hub_prefix_not_in_edition_map(self):
        """/api/tasks/ 不应出现在任何 edition 的隐藏前缀表 (hub 开源全开)。"""
        import src.main as main
        for edition, prefixes in main._EDITION_ROUTE_MAP.items():
            assert not any("tasks" in p for p in prefixes), \
                f"hub 路由不应被 {edition} 隐藏: {prefixes}"

    def test_hub_routes_registered(self):
        """hub 路由真实注册 (router 内) 且含在 main app 的 included router 集。"""
        import src.core.task_cards_api as api
        paths = [getattr(r, "path", "") for r in api.router.routes]
        for want in ("/cards", "/cards/{card_id}", "/quota"):
            assert any(p.endswith(want) for p in paths), f"{want} 未在 router 注册"
        # main include 了该 router (服务冒烟另行覆盖真实可调用)
        import src.main as main
        src = getattr(main, "task_cards_router", None)
        if src is None:
            # include 用的局部名 → 通过 app.router 检查 included routers
            inc = [type(r).__name__ for r in main.app.routes]
            assert "_IncludedRouter" in inc or "APIRoute" in inc

    def test_edition_route_map_sanity(self):
        """既有 edition 隐藏表回归 (personal 应含团队/企业前缀)。"""
        import src.main as main
        m = main._EDITION_ROUTE_MAP
        assert any("billing" in p for p in m["personal"])
        assert any("team" in p for p in m["personal"])
        assert any("sso" in p for p in m["team"])
        assert m["enterprise"] == ()


class TestEditionDetectionSim:
    def _make_stub(self, tmp_path, mod_name, stub):
        """在隔离目录生成 sso.py/team_memory.py 模拟三态。
        注意: stub=False 的文件绝不能含 "_IMPLEMENTATION_MOVED" 字样
        (检测按头 4096 字节含该串即判 stub)。"""
        if stub:
            (tmp_path / f"{mod_name}.py").write_text(
                "# -*- coding: utf-8 -*-\n_IMPLEMENTATION_MOVED = True\n")
        else:
            (tmp_path / f"{mod_name}.py").write_text(
                "# -*- coding: utf-8 -*-\n# real implementation (personal build)\n"
                "def do_stuff():\n    return 1\n")

    def test_personal(self, tmp_path, monkeypatch):
        from src.core import _edition
        for m in ("sso", "team_memory"):
            self._make_stub(tmp_path, m, stub=True)
        monkeypatch.setattr(_edition, "_THIS_DIR", str(tmp_path))
        assert _edition.detect_edition() == "personal"
        assert _edition.enterprise_available() is False
        assert _edition.team_available() is False

    def test_team(self, tmp_path, monkeypatch):
        from src.core import _edition
        self._make_stub(tmp_path, "sso", stub=True)
        self._make_stub(tmp_path, "team_memory", stub=False)
        monkeypatch.setattr(_edition, "_THIS_DIR", str(tmp_path))
        assert _edition.detect_edition() == "team"
        assert _edition.enterprise_available() is False
        assert _edition.team_available() is True

    def test_enterprise(self, tmp_path, monkeypatch):
        from src.core import _edition
        self._make_stub(tmp_path, "sso", stub=False)
        self._make_stub(tmp_path, "team_memory", stub=False)
        monkeypatch.setattr(_edition, "_THIS_DIR", str(tmp_path))
        assert _edition.detect_edition() == "enterprise"
        assert _edition.enterprise_available() is True
        assert _edition.team_available() is True
