# -*- coding: utf-8 -*-
"""SMA Phase 3 轨迹过程记忆守门 — 落盘/检索/注入/隔离."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import trajectories as T


@pytest.fixture()
def traj_home(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "_TRAJ_DIR", tmp_path / "trajectories")
    return tmp_path


def test_save_and_load_success_only(traj_home):
    tid = T.save_trajectory("部署 nginx 反代", [{"tool": "terminal", "action": "apt install"}],
                            "安装完成, 反代生效", tags=["deploy", "nginx"])
    T.save_trajectory("失败案例", [{"tool": "terminal"}], "报错", outcome="fail")
    recs = T.load_trajectories("success")
    assert len(recs) == 1 and recs[0]["id"] == tid


def test_search_similar_keyword_overlap(traj_home):
    T.save_trajectory("nginx 反代配置部署", [{"tool": "terminal"}], "done", tags=["deploy"])
    hits = T.search_similar("nginx 反代 部署问题", top_k=3)
    assert hits and "nginx" in hits[0]["task"]


def test_search_empty_returns_no_injection(traj_home):
    assert T.build_injection("完全无关的量子物理问题") == ""


def test_build_injection_contains_trajectory(traj_home):
    T.save_trajectory("kafka 集群迁移", [{"tool": "terminal", "action": "step1"},
                                          {"tool": "edit_file", "action": "step2"}],
                      "迁移完成要点: 先切 consumer", tags=["kafka"])
    inj = T.build_injection("kafka 迁移怎么做")
    assert "过程参考" in inj and "kafka" in inj and "解法步骤" in inj


def test_atomic_write_no_tmp(traj_home):
    T.save_trajectory("tmp 残留检查", [], "ok")
    assert not list(T._dir().glob("*.tmp"))
