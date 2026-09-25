# -*- coding: utf-8 -*-
"""开源库组通道 stub 守门 — 完整实现已迁 meshctx-team (ENTERPRISE_MIGRATION 模式).

三库隔离 (用户 2026-09-22 确认): 开源 meshctx (AGPL) / 私有 meshctx-team /
私有 meshctx-enterprise — 团队协作功能不得回流开源库。
"""
def test_cluster_groups_is_stub():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "cluster" / "cluster_groups.py"
    head = p.read_text(encoding="utf-8")[:4096]
    assert "_ENTERPRISE_FEATURE_MOVED" in head, "stub 标记丢失 (防实现回流)"


def test_cluster_groups_import_raises_team_feature():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cluster"))
    import cluster_groups
    try:
        cluster_groups.group_send  # noqa: B018  任意符号访问
        raise AssertionError("stub 不应暴露实现符号")
    except cluster_groups.TeamFeatureError:
        pass  # 预期
