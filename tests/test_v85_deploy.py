"""v2.85 Auto Deploy — 测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def pipeline():
    from src.core.auto_deploy import AutoDeployPipeline
    return AutoDeployPipeline(project_root=Path(__file__).parent.parent)


class TestPipeline:
    def test_check(self, pipeline):
        ok, msg = pipeline._check()
        assert ok is True

    def test_stats(self, pipeline):
        stats = pipeline.get_stats()
        assert "command" in stats
        assert stats["command"] == "meshctx deploy"

    def test_deploy_fast_check(self, pipeline):
        """只测check步骤(不跑全量)"""
        ok, msg = pipeline._check()
        assert "2.84" in msg or "2." in msg


class TestDeployResult:
    def test_create(self):
        from src.core.auto_deploy import DeployResult, DeployStage
        r = DeployResult(status=DeployStage.DONE, duration_seconds=10.5)
        assert r.status == DeployStage.DONE
        assert r.duration_seconds == 10.5
