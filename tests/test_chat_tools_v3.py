"""测试 chat_tools v3 — 11工具验证"""
import pytest, tempfile, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.chat_tools import (
    _patch, _edit_file, _git_diff, _git_log, _git_show,
    _web_extract, _lint_check, execute_tool, TOOL_EXECUTORS, TOOLS_OPENAI
)


class TestNewTools:
    """测试新增的5个工具"""

    def test_patch_unique(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("hello\nworld\nhello\n")
            path = f.name
        try:
            result = _patch(path, "hello", "hi", replace_all=True)
            assert "已修补" in result
            with open(path) as f:
                assert f.read() == "hi\nworld\nhi\n"
        finally:
            os.unlink(path)

    def test_patch_multiple_without_flag(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("hello world\nhello there\n")
            path = f.name
        try:
            result = _patch(path, "hello", "hi")
            assert "匹配到 2 处" in result
        finally:
            os.unlink(path)

    def test_patch_multiple_with_flag(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("hello world\nhello there\n")
            path = f.name
        try:
            result = _patch(path, "hello", "hi", replace_all=True)
            assert "已修补" in result
            assert "2处" in result
        finally:
            os.unlink(path)

    def test_patch_not_found(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("hello\n")
            path = f.name
        try:
            result = _patch(path, "nonexistent", "hi")
            assert "未找到" in result
        finally:
            os.unlink(path)

    def test_edit_file_alias(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("old line\n")
            path = f.name
        try:
            result = _edit_file(path, "old line", "new line")
            assert "已修补" in result
        finally:
            os.unlink(path)

    def test_git_diff(self):
        result = _git_diff(".")
        # 在 git 仓库中应该有输出（或无变更）
        assert isinstance(result, str)

    def test_git_log(self):
        result = _git_log(".", 3)
        assert isinstance(result, str)

    def test_git_show(self):
        result = _git_show("HEAD", "")
        assert isinstance(result, str)

    def test_web_extract_invalid_url(self):
        result = _web_extract("http://localhost:1/nonexistent")
        assert isinstance(result, str)

    def test_lint_check_auto(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def foo():\n    pass\n")
            path = f.name
        try:
            result = _lint_check(path)
            assert isinstance(result, str)
        finally:
            os.unlink(path)

    def test_lint_check_unknown_ext(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xyz', delete=False) as f:
            f.write("hello")
            path = f.name
        try:
            result = _lint_check(path)
            assert "无法自动检测" in result
        finally:
            os.unlink(path)

    def test_lint_check_dangerous_path(self):
        result = _lint_check("/tmp/evil'; rm -rf /; echo '")
        assert "危险字符" in result or "文件不存在" in result


class TestToolRegistry:
    """测试工具注册表完整性"""

    def test_11_tools_registered(self):
        assert len(TOOL_EXECUTORS) >= 11, f"Expected >=11 tools, got {len(TOOL_EXECUTORS)}"

    def test_all_new_tools_in_executors(self):
        for name in ["patch", "edit_file", "git_diff", "git_log", "git_show", "web_extract", "lint_check"]:
            assert name in TOOL_EXECUTORS, f"Missing: {name}"

    def test_all_new_tools_in_openai(self):
        names = {t["function"]["name"] for t in TOOLS_OPENAI}
        for name in ["patch", "edit_file", "git_diff", "git_log", "git_show", "web_extract", "lint_check"]:
            assert name in names, f"Missing in TOOLS_OPENAI: {name}"

    def test_execute_tool_unknown(self):
        result = execute_tool("nonexistent_tool", {})
        assert "未知工具" in result

    def test_tool_icons_complete(self):
        from src.chat_tools import TOOL_ICONS
        for name in TOOL_EXECUTORS:
            assert name in TOOL_ICONS, f"Missing icon for: {name}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
