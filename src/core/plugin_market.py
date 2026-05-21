"""Plugin Marketplace — v2.65
━━━━━━━━━━━━━━━━━━━━━━━━
一行命令安装/移除插件。内建15个官方插件，支持第三方贡献。

解决痛点: "Docker + 5 ENV vars + PhD required" → "meshctx plugin install slack"
"""
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PluginStatus(Enum):
    AVAILABLE = "available"
    INSTALLED = "installed"
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class PluginInfo:
    """插件信息"""
    name: str
    version: str
    description: str
    category: str = "utility"
    author: str = "meshctx"
    status: PluginStatus = PluginStatus.AVAILABLE
    dependencies: List[str] = field(default_factory=list)
    install_command: str = ""
    size_kb: int = 0
    downloads: int = 0
    rating: float = 0.0


class PluginMarketplace:
    """插件市场"""

    # 内建15个官方插件
    _OFFICIAL_PLUGINS: Dict[str, PluginInfo] = {
        # ── Gateway 插件 ──
        "slack-gateway": PluginInfo(
            name="slack-gateway", version="1.0.0",
            description="Slack集成 — Agent通过Slack接收指令和回复",
            category="gateway",
            install_command="pip install slack-sdk",
            size_kb=45,
        ),
        "discord-gateway": PluginInfo(
            name="discord-gateway", version="1.0.0",
            description="Discord集成 — Agent作为Discord Bot运行",
            category="gateway",
            install_command="pip install discord.py",
            size_kb=52,
        ),
        "telegram-gateway": PluginInfo(
            name="telegram-gateway", version="1.0.0",
            description="Telegram集成 — 通过Bot API接收指令",
            category="gateway",
            install_command="pip install python-telegram-bot",
            size_kb=38,
        ),
        "wechat-gateway": PluginInfo(
            name="wechat-gateway", version="1.0.0",
            description="企业微信集成 — 飞书Webhook双向通信",
            category="gateway",
            install_command="pip install requests",
            size_kb=28,
        ),
        # ── 记忆插件 ──
        "mem0-backend": PluginInfo(
            name="mem0-backend", version="1.0.0",
            description="Mem0记忆后端 — 使用Mem0替代默认SDM",
            category="memory",
            install_command="pip install mem0ai",
            size_kb=120,
        ),
        "honcho-backend": PluginInfo(
            name="honcho-backend", version="1.0.0",
            description="Honcho用户级记忆 — 多用户隔离记忆",
            category="memory",
            install_command="pip install honcho-ai",
            size_kb=95,
        ),
        "qdrant-backend": PluginInfo(
            name="qdrant-backend", version="1.0.0",
            description="Qdrant向量数据库 — 替代默认TF-IDF",
            category="memory",
            install_command="pip install qdrant-client",
            size_kb=210,
        ),
        # ── 安全插件 ──
        "audit-log": PluginInfo(
            name="audit-log", version="1.0.0",
            description="审计日志 — 所有操作完整记录不可篡改",
            category="security",
            size_kb=35,
        ),
        "sandbox-executor": PluginInfo(
            name="sandbox-executor", version="1.0.0",
            description="沙盒执行器 — Docker隔离执行不受信任代码",
            category="security",
            install_command="pip install docker",
            size_kb=68,
        ),
        # ── 工具插件 ──
        "web-browser": PluginInfo(
            name="web-browser", version="1.0.0",
            description="Web浏览器 — Agent可以浏览网页获取实时信息",
            category="tools",
            install_command="pip install playwright",
            size_kb=340,
        ),
        "code-interpreter": PluginInfo(
            name="code-interpreter", version="1.0.0",
            description="代码解释器 — E2B沙盒执行Python/JS/SQL",
            category="tools",
            install_command="pip install e2b",
            size_kb=85,
        ),
        "voice-tts": PluginInfo(
            name="voice-tts", version="1.0.0",
            description="语音合成 — TTS将文本转为语音输出",
            category="tools",
            install_command="pip install edge-tts",
            size_kb=155,
        ),
        "voice-stt": PluginInfo(
            name="voice-stt", version="1.0.0",
            description="语音识别 — STT将语音转为文本输入",
            category="tools",
            install_command="pip install openai-whisper",
            size_kb=2500,
        ),
        # ── 监控插件 ──
        "prometheus-exporter": PluginInfo(
            name="prometheus-exporter", version="1.0.0",
            description="Prometheus指标导出 — /metrics端点",
            category="monitoring",
            install_command="pip install prometheus-client",
            size_kb=40,
        ),
        "grafana-dashboard": PluginInfo(
            name="grafana-dashboard", version="1.0.0",
            description="Grafana仪表盘模板 — 一键导入",
            category="monitoring",
            size_kb=15,
        ),
    }

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path.home() / ".meshctx" / "plugins"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._installed: Dict[str, PluginInfo] = {}
        self._load_state()

    def _load_state(self):
        """加载已安装插件状态"""
        state_file = self.data_dir / "state.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                for name, info in data.items():
                    # 从官方插件恢复完整info
                    if name in self._OFFICIAL_PLUGINS:
                        p = self._OFFICIAL_PLUGINS[name]
                        p.status = PluginStatus(info.get("status", "active"))
                        self._installed[name] = p
            except Exception as e:
                logger.warning(f"Plugin state load failed: {e}")

    def _save_state(self):
        """保存插件状态"""
        state_file = self.data_dir / "state.json"
        data = {name: {
            "name": p.name, "version": p.version,
            "status": p.status.value, "category": p.category,
        } for name, p in self._installed.items()}
        state_file.write_text(json.dumps(data, indent=2))

    # ── Marketplace API ───────────────────────────────

    def search(self, query: str = "", category: str = "") -> List[PluginInfo]:
        """搜索插件"""
        results = []
        for name, plugin in self._OFFICIAL_PLUGINS.items():
            if category and plugin.category != category:
                continue
            if query and query.lower() not in name.lower() and \
               query.lower() not in plugin.description.lower():
                continue
            # Override with installed status
            if name in self._installed:
                plugin.status = self._installed[name].status
            results.append(plugin)
        return results

    def install(self, name: str, auto_deps: bool = True) -> Dict[str, Any]:
        """安装插件"""
        if name not in self._OFFICIAL_PLUGINS:
            return {"success": False, "error": f"插件 '{name}' 不存在"}

        plugin = self._OFFICIAL_PLUGINS[name]

        if name in self._installed and \
           self._installed[name].status == PluginStatus.ACTIVE:
            return {"success": False, "error": f"插件 '{name}' 已安装"}

        # 安装依赖
        deps_ok = True
        if plugin.install_command:
            try:
                result = subprocess.run(
                    plugin.install_command.split(),
                    capture_output=True, text=True, timeout=60
                )
                deps_ok = result.returncode == 0
            except Exception as e:
                deps_ok = False
                logger.warning(f"Plugin {name} dep install failed: {e}")

        # 标记已安装
        plugin.status = PluginStatus.ACTIVE
        plugin.downloads += 1
        self._installed[name] = plugin
        self._save_state()

        return {
            "success": True,
            "plugin": name,
            "version": plugin.version,
            "dependencies_ok": deps_ok,
            "message": f"✅ {plugin.name} v{plugin.version} 安装成功!",
        }

    def uninstall(self, name: str) -> Dict[str, Any]:
        """卸载插件"""
        if name not in self._installed:
            return {"success": False, "error": f"插件 '{name}' 未安装"}

        del self._installed[name]
        self._save_state()
        return {"success": True, "message": f"🗑️ {name} 已卸载"}

    def list_installed(self) -> List[PluginInfo]:
        """列出已安装插件"""
        return list(self._installed.values())

    def enable(self, name: str) -> Dict:
        """启用插件"""
        if name not in self._installed:
            return self.install(name)
        self._installed[name].status = PluginStatus.ACTIVE
        self._save_state()
        return {"success": True, "message": f"✅ {name} 已启用"}

    def disable(self, name: str) -> Dict:
        """禁用插件"""
        if name not in self._installed:
            return {"success": False, "error": f"插件 '{name}' 未安装"}
        self._installed[name].status = PluginStatus.DISABLED
        self._save_state()
        return {"success": True, "message": f"⏸️ {name} 已禁用"}

    # ── Categories ────────────────────────────────────

    def get_categories(self) -> List[str]:
        cats = set(p.category for p in self._OFFICIAL_PLUGINS.values())
        return sorted(cats)

    def get_stats(self) -> Dict:
        return {
            "total_plugins": len(self._OFFICIAL_PLUGINS),
            "installed": len(self._installed),
            "active": sum(
                1 for p in self._installed.values()
                if p.status == PluginStatus.ACTIVE
            ),
            "categories": self.get_categories(),
            "one_liner": "meshctx plugin install <name>  # 一行安装",
        }


# 单例
_marketplace: Optional[PluginMarketplace] = None


def get_plugin_marketplace() -> PluginMarketplace:
    global _marketplace
    if _marketplace is None:
        _marketplace = PluginMarketplace()
    return _marketplace
