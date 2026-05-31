"""v3.55 Plugin Hot-Reload — tests"""
import pytest, tempfile, os
from pathlib import Path
from src.core.plugin_hotreload import PluginHotReload, PluginMeta, get_hotreload

class TestHotReload:
    def test_scan_empty(self):
        with tempfile.TemporaryDirectory() as d:
            hr = PluginHotReload(d)
            assert len(hr.scan()) == 0

    def test_scan_discovers(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,"test_plugin.py").write_text("VERSION='1.0'\ndef run(): return 'ok'\n")
            hr = PluginHotReload(d)
            found = hr.scan()
            assert len(found) == 1
            assert found[0].name == "test_plugin"

    def test_load_plugin(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,"hello.py").write_text("VERSION='1.0'\ndef greet(): return 'hi'\n")
            hr = PluginHotReload(d)
            hr.scan()
            assert hr.load("hello")
            assert hr._plugins["hello"].loaded

    def test_unload(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,"p.py").write_text("VERSION='1'\n")
            hr = PluginHotReload(d)
            hr.scan(); hr.load("p")
            assert hr.unload("p")
            assert not hr._plugins["p"].loaded

    def test_check_updates(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d,"p.py")
            p.write_text("VERSION='1'\n")
            hr = PluginHotReload(d)
            hr.scan(); hr.load("p")
            p.write_text("VERSION='2'\n")
            updates = hr.check_updates()
            assert len(updates) == 1

    def test_reload(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d,"p.py")
            p.write_text("VERSION='1'\ndef v(): return 1\n")
            hr = PluginHotReload(d)
            hr.scan(); hr.load("p")
            assert hr.reload("p")

    def test_stats(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,"p.py").write_text("VERSION='1'\n")
            hr = PluginHotReload(d)
            hr.scan()
            stats = hr.get_stats()
            assert stats["plugins_total"] == 1

    def test_singleton(self):
        with tempfile.TemporaryDirectory() as d:
            assert get_hotreload(d) is get_hotreload(d)
