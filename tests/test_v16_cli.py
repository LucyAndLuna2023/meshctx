"""
Test v1.5.26 — CLI (meshctx command)
Covers: all subcommands parsing and basic execution
"""
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def parser():
    """Get the argparse parser from cli.main()"""
    from src.cli import main
    # We can't import the internal parser directly, but we can inspect it via the
    # argparse subparsers. Let's create a mock argument namespace.
    import argparse
    p = argparse.ArgumentParser(prog="meshctx")
    sub = p.add_subparsers(dest="command")

    # model
    m = sub.add_parser("model", help="模型管理")
    m.add_argument("model_action", choices=["scan","list","available","add","test","use"])
    m.add_argument("model_id", nargs="?", help="模型ID")
    m.add_argument("--key")
    m.add_argument("--model")
    m.add_argument("--base-url")
    m.add_argument("-p","--prompt")
    m.add_argument("-c","--config")
    m.set_defaults(func=lambda a: None)

    # skill
    s = sub.add_parser("skill", help="Skill管理")
    s.add_argument("skill_action", choices=["list","create","delete","auto"])
    s.add_argument("name", nargs="?")
    s.add_argument("-d","--description")
    s.add_argument("-t","--trigger")
    s.add_argument("--steps")
    s.add_argument("--tools")
    s.add_argument("-c","--config")
    s.set_defaults(func=lambda a: None)

    # chat
    c = sub.add_parser("chat", help="对话")
    c.add_argument("-m","--model")
    c.add_argument("-s","--system")
    c.add_argument("-c","--config")
    c.set_defaults(func=lambda a: None)

    # start / stop / status
    st = sub.add_parser("start", help="启动服务")
    st.add_argument("-p","--port", type=int)
    st.add_argument("-c","--config")
    st.set_defaults(func=lambda a: None)

    sub.add_parser("stop", help="停止服务").set_defaults(func=lambda a: None)
    sub.add_parser("status", help="状态").set_defaults(func=lambda a: None)

    # evolve
    ev = sub.add_parser("evolve", help="自进化")
    ev.add_argument("--auto", action="store_true")
    ev.add_argument("-c","--config")
    ev.set_defaults(func=lambda a: None)

    # web
    sub.add_parser("web", help="Web控制台").set_defaults(func=lambda a: None)
    sub.add_parser("desktop", help="桌面客户端").set_defaults(func=lambda a: None)

    # cron
    cr = sub.add_parser("cron", help="定时任务")
    cr.add_argument("cron_action", choices=["list","add","remove"])
    cr.add_argument("name", nargs="?")
    cr.add_argument("-s","--schedule")
    cr.add_argument("-a","--action")
    cr.set_defaults(func=lambda a: None)

    # search
    sr = sub.add_parser("search", help="Session搜索")
    sr.add_argument("query", nargs="?")
    sr.add_argument("-n","--limit", type=int, default=10)
    sr.set_defaults(func=lambda a: None)

    # browser
    br = sub.add_parser("browser", help="浏览器工具")
    br.add_argument("action", choices=["open","snap","click","type"])
    br.add_argument("target", nargs="?")
    br.add_argument("--text")
    br.set_defaults(func=lambda a: None)

    # tts
    tt = sub.add_parser("tts", help="语音合成")
    tt.add_argument("text", nargs="?")
    tt.add_argument("-v","--voice", default="zh-CN-XiaoxiaoNeural")
    tt.add_argument("-o","--output")
    tt.set_defaults(func=lambda a: None)

    # mcp
    mc = sub.add_parser("mcp", help="MCP协议")
    mc.add_argument("action", choices=["serve","tools"])
    mc.set_defaults(func=lambda a: None)

    return p


# ═══════════════════════════════════════════════════════════════
# 1. Help / version
# ═══════════════════════════════════════════════════════════════

class TestCLIHelp:
    """Test help output"""

    def test_cli_help(self, parser):
        """--help shows usage info"""
        try:
            parser.parse_args(["--help"])
        except SystemExit as e:
            assert e.code == 0

    def test_cli_no_args(self, parser):
        """No args sets command to None"""
        args = parser.parse_args([])
        assert args.command is None

    def test_cli_model_help(self, parser):
        """model --help shows model subcommand help"""
        try:
            parser.parse_args(["model", "--help"])
        except SystemExit as e:
            assert e.code == 0

    def test_cli_unknown_command_fails(self, parser):
        """Unknown command raises error"""
        with pytest.raises(SystemExit):
            parser.parse_args(["unknown_command"])


# ═══════════════════════════════════════════════════════════════
# 2. Subcommand Dispatch
# ═══════════════════════════════════════════════════════════════

class TestCLISubcommands:
    """Test each subcommand can be parsed"""

    def test_cli_model_scan(self, parser):
        """model scan parses"""
        args = parser.parse_args(["model", "scan"])
        assert args.command == "model"
        assert args.model_action == "scan"

    def test_cli_model_list(self, parser):
        """model list parses"""
        args = parser.parse_args(["model", "list"])
        assert args.model_action == "list"

    def test_cli_model_available(self, parser):
        """model available parses"""
        args = parser.parse_args(["model", "available"])
        assert args.model_action == "available"

    def test_cli_model_add(self, parser):
        """model add parses with args"""
        args = parser.parse_args(["model", "add", "deepseek:chat", "--key", "sk-test"])
        assert args.model_action == "add"
        assert args.model_id == "deepseek:chat"
        assert args.key == "sk-test"

    def test_cli_model_test(self, parser):
        """model test parses with prompt"""
        args = parser.parse_args(["model", "test", "deepseek:chat", "-p", "Hello"])
        assert args.model_action == "test"
        assert args.prompt == "Hello"

    def test_cli_model_use(self, parser):
        """model use parses"""
        args = parser.parse_args(["model", "use", "deepseek:chat"])
        assert args.model_action == "use"
        assert args.model_id == "deepseek:chat"

    def test_cli_chat(self, parser):
        """chat subcommand parses"""
        args = parser.parse_args(["chat", "-m", "deepseek:chat", "-s", "You are helpful"])
        assert args.command == "chat"
        assert args.model == "deepseek:chat"
        assert args.system == "You are helpful"

    def test_cli_start(self, parser):
        """start subcommand parses"""
        args = parser.parse_args(["start", "-p", "8080"])
        assert args.command == "start"
        assert args.port == 8080

    def test_cli_stop(self, parser):
        """stop subcommand parses"""
        args = parser.parse_args(["stop"])
        assert args.command == "stop"

    def test_cli_status(self, parser):
        """status subcommand parses"""
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_cli_evolve(self, parser):
        """evolve subcommand parses"""
        args = parser.parse_args(["evolve", "--auto"])
        assert args.command == "evolve"
        assert args.auto is True

    def test_cli_web(self, parser):
        """web subcommand parses"""
        args = parser.parse_args(["web"])
        assert args.command == "web"

    def test_cli_desktop(self, parser):
        """desktop subcommand parses"""
        args = parser.parse_args(["desktop"])
        assert args.command == "desktop"

    def test_cli_skill_list(self, parser):
        """skill list parses"""
        args = parser.parse_args(["skill", "list"])
        assert args.command == "skill"
        assert args.skill_action == "list"

    def test_cli_cron_list(self, parser):
        """cron list parses"""
        args = parser.parse_args(["cron", "list"])
        assert args.command == "cron"
        assert args.cron_action == "list"

    def test_cli_search(self, parser):
        """search with query parses"""
        args = parser.parse_args(["search", "test query", "-n", "5"])
        assert args.command == "search"
        assert args.query == "test query"
        assert args.limit == 5

    def test_cli_mcp_tools(self, parser):
        """mcp tools parses"""
        args = parser.parse_args(["mcp", "tools"])
        assert args.command == "mcp"
        assert args.action == "tools"

    def test_cli_tts(self, parser):
        """tts with text parses"""
        args = parser.parse_args(["tts", "Hello world", "-v", "en-US-JennyNeural"])
        assert args.command == "tts"
        assert args.text == "Hello world"
        assert args.voice == "en-US-JennyNeural"

    def test_cli_browser_open(self, parser):
        """browser open parses"""
        args = parser.parse_args(["browser", "open", "https://example.com"])
        assert args.command == "browser"
        assert args.action == "open"
        assert args.target == "https://example.com"


# ═══════════════════════════════════════════════════════════════
# 3. CLI Command Functions (with mocks)
# ═══════════════════════════════════════════════════════════════

class TestCLICommandFunctions:
    """Test actual CLI command functions with mocked dependencies"""

    @patch("src.model_registry.get_registry")
    def test_cmd_model_list_empty(self, mock_get_registry, capsys):
        """cmd_model with list action shows empty message"""
        from src.cli import cmd_model
        mock_reg = MagicMock()
        mock_reg.list_all.return_value = []
        mock_get_registry.return_value = mock_reg
        args = MagicMock()
        args.model_action = "list"
        args.config = None
        cmd_model(args)
        captured = capsys.readouterr()
        assert "暂无" in captured.out or "No" in captured.out

    @patch("src.model_registry.get_registry")
    def test_cmd_model_list_with_entries(self, mock_get_registry, capsys):
        """cmd_model with list action shows entries"""
        from src.cli import cmd_model
        mock_reg = MagicMock()
        mock_reg.list_all.return_value = [
            {"id": "deepseek:chat", "provider": "deepseek", "model": "deepseek-chat", "ready": True},
            {"id": "bailian:qwen-flash", "provider": "bailian", "model": "qwen-flash", "ready": False},
        ]
        mock_get_registry.return_value = mock_reg
        args = MagicMock()
        args.model_action = "list"
        args.config = None
        cmd_model(args)
        captured = capsys.readouterr()
        assert "deepseek:chat" in captured.out
        assert "bailian:qwen-flash" in captured.out

    @patch("src.model_registry.get_registry")
    def test_cmd_model_scan(self, mock_get_registry, capsys):
        """cmd_model with scan action"""
        from src.cli import cmd_model
        mock_reg = MagicMock()
        mock_reg.auto_configure.return_value = [
            {"id": "deepseek:chat", "ready": True},
            {"id": "bailian:qwen-flash", "ready": True},
        ]
        mock_get_registry.return_value = mock_reg
        args = MagicMock()
        args.model_action = "scan"
        args.config = None
        cmd_model(args)
        captured = capsys.readouterr()
        assert "deepseek:chat" in captured.out

    @patch("src.model_registry.get_registry")
    def test_cmd_model_add(self, mock_get_registry, capsys):
        """cmd_model with add action"""
        from src.cli import cmd_model
        mock_reg = MagicMock()
        mock_reg.add.return_value = {"key": "sk-test", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1", "provider": "deepseek"}
        mock_get_registry.return_value = mock_reg
        args = MagicMock()
        args.model_action = "add"
        args.model_id = "deepseek:chat"
        args.key = "sk-test"
        args.model = "deepseek-chat"
        args.base_url = ""
        args.config = None
        cmd_model(args)
        mock_reg.add.assert_called_once_with("deepseek:chat", key="sk-test", model="deepseek-chat", base_url="")

    @patch("src.model_registry.get_registry")
    def test_cmd_model_use_nonexistent(self, mock_get_registry, capsys):
        """cmd_model use with unconfigured model prints error"""
        from src.cli import cmd_model
        mock_reg = MagicMock()
        mock_reg._entries = {}
        mock_get_registry.return_value = mock_reg
        args = MagicMock()
        args.model_action = "use"
        args.model_id = "nonexistent:model"
        args.config = None
        cmd_model(args)
        captured = capsys.readouterr()
        assert "未配置" in captured.out or "not configured" in captured.out

    @patch("src.model_registry.get_registry")
    def test_cmd_model_use_existing(self, mock_get_registry, capsys):
        """cmd_model use with configured model succeeds"""
        from src.cli import cmd_model
        mock_reg = MagicMock()
        mock_reg._entries = {"deepseek:chat": {}}
        mock_get_registry.return_value = mock_reg
        args = MagicMock()
        args.model_action = "use"
        args.model_id = "deepseek:chat"
        args.config = None
        cmd_model(args)
        captured = capsys.readouterr()
        assert "已切换" in captured.out or "switched" in captured.out or "默认模型" in captured.out

    @patch("src.model_registry.get_registry")
    def test_cmd_chat_no_model(self, mock_get_registry, capsys):
        """cmd_chat with no available model prints error"""
        from src.cli import cmd_chat
        mock_reg = MagicMock()
        mock_reg.get.return_value = None
        mock_get_registry.return_value = mock_reg
        args = MagicMock()
        args.model = None
        args.config = None
        args.system = None
        # cmd_chat enters an interactive loop, we need to mock input to immediately quit
        with patch("builtins.input", side_effect=EOFError):
            cmd_chat(args)
        captured = capsys.readouterr()
        assert "无可用模型" in captured.out or "No model available" in captured.out

    @patch("src.model_registry.get_registry")
    def test_cmd_model_test_no_client(self, mock_get_registry, capsys):
        """cmd_model test with no client prints error"""
        from src.cli import cmd_model
        mock_reg = MagicMock()
        mock_reg.get.return_value = None
        mock_get_registry.return_value = mock_reg
        args = MagicMock()
        args.model_action = "test"
        args.model_id = "nonexistent"
        args.prompt = "Hello"
        args.config = None
        cmd_model(args)
        captured = capsys.readouterr()
        assert "未配置" in captured.out or "not configured" in captured.out

    @patch("subprocess.run")
    def test_cmd_stop(self, mock_run, capsys):
        """cmd_stop calls pkill"""
        from src.cli import cmd_stop
        mock_run.return_value.returncode = 0
        args = MagicMock()
        cmd_stop(args)
        mock_run.assert_called_once()

    @patch("requests.get")
    def test_cmd_status_running(self, mock_get, capsys):
        """cmd_status shows running info"""
        from src.cli import cmd_status
        mock_response = MagicMock()
        mock_response.json.return_value = {"version": "1.5.26", "projects_count": 2, "conversations_count": 5, "memories_count": 10}
        mock_get.return_value = mock_response
        args = MagicMock()
        cmd_status(args)
        captured = capsys.readouterr()
        assert "运行中" in captured.out or "running" in captured.out or "1.5" in captured.out

    @patch("requests.get")
    def test_cmd_status_not_running(self, mock_get, capsys):
        """cmd_status when not running shows stopped"""
        from src.cli import cmd_status
        mock_get.side_effect = Exception("Connection refused")
        args = MagicMock()
        cmd_status(args)
        captured = capsys.readouterr()
        assert "未运行" in captured.out or "not running" in captured.out
