# -*- coding: utf-8 -*-
"""002codex e39511de P1 守门 — 非主线程 import src.main 不再 ValueError.

src/main.py 模块级 signal 注册 (SIGSEGV/SIGBUS) 在非主线程 import 时抛
ValueError (Python: handler 只能主线程注册) — desktop/线程化部署形态炸。
修: 主线程守卫 (threading.current_thread() is main_thread 才注册)。
"""
import threading
import queue
import sys
from pathlib import Path


def test_main_thread_import_ok():
    import src.main  # noqa: F401
    assert True


def test_non_main_thread_import_ok(tmp_path, monkeypatch):
    """子线程 import src.main — 修复前必 ValueError (002codex 场景)."""
    res = queue.Queue()

    def worker():
        try:
            import importlib
            import src.main
            importlib.reload(src.main)
            res.put("OK")
        except ValueError as e:
            res.put(f"ValueError: {e}")
        except Exception as e:
            res.put(f"{type(e).__name__}: {e}")

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=120)
    assert res.get() == "OK"


def test_signal_handlers_registered_in_main_thread():
    """主线程注册路径语义保持: SIGSEGV handler 注册后可查 (getsignal)."""
    import signal
    import src.main  # 确保注册路径已执行
    # 主线程上 SIGSEGV 的 handler 应非默认 (注册语义保持)
    assert signal.getsignal(signal.SIGSEGV) is not signal.SIG_DFL
