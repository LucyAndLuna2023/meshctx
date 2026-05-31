"""v3.57 Deploy Engine — tests"""
import pytest
from src.core.deploy_engine import DeployEngine, DeployTarget, get_deploy_engine

class TestDeployEngine:
    def test_init(self):
        e = DeployEngine()
        assert e._project_root.exists()

    def test_detect_environment(self):
        e = DeployEngine()
        env = e.detect_environment()
        assert "os" in env
        assert "python" in env

    def test_generate_systemd_unit(self):
        e = DeployEngine()
        unit = e.generate_systemd_unit(DeployTarget(user="test",path="/opt/test"))
        assert "MeshCtx" in unit
        assert "systemd" in unit.lower() or "Service" in unit

    def test_backup_current(self):
        e = DeployEngine()
        path = e.backup_current()
        assert path is not None

    def test_get_stats(self):
        e = DeployEngine()
        stats = e.get_stats()
        assert "deployments" in stats
        assert "backups" in stats

    def test_singleton(self):
        assert get_deploy_engine() is get_deploy_engine()
