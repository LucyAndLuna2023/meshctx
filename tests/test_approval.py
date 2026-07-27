"""approval 审批引擎测试"""
import pytest

class TestApprovalModes:
    """三级审批模式"""

    def test_manual_mode_all_requires_approval(self):
        pytest.skip("TODO: 非白名单命令 → requires_approval=True")

    def test_smart_mode_safe_auto_approve(self):
        pytest.skip("TODO: 'ls -la' → requires_approval=False")

    def test_off_mode_skip_all(self):
        pytest.skip("TODO: 'rm -rf /' 在 off 模式 → requires_approval=False")

    def test_yolo_override(self):
        pytest.skip("TODO: yolo=True → 所有命令跳过审批")


class TestSafeWhitelist:
    """安全白名单"""

    def test_ls_is_safe(self):
        pytest.skip("TODO: 'ls' → risk=LOW, requires_approval=False")

    def test_git_status_is_safe(self):
        pytest.skip("TODO: 'git status' → risk=LOW")


class TestDangerousBlacklist:
    """危险黑名单"""

    def test_rm_rf_root_is_critical(self):
        pytest.skip("TODO: 'rm -rf /' → CRITICAL, action=block")

    def test_dd_write_block_device(self):
        pytest.skip("TODO: 'dd if=... of=/dev/sda' → CRITICAL")

    def test_curl_pipe_bash(self):
        pytest.skip("TODO: 'curl ... | bash' → HIGH")

    def test_git_force_push(self):
        pytest.skip("TODO: 'git push --force' → HIGH")


class TestModeSwitch:
    """模式切换"""

    def test_switch_manual_to_smart(self):
        pytest.skip("TODO: set_mode('smart') → mode=='smart'")

    def test_invalid_mode_raises(self):
        pytest.skip("TODO: set_mode('invalid') → ValueError")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
