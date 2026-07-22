"""
meshctx Hermes Connector Plugin — v1.0
使 meshctx 与 Hermes Agent 集群协同工作。

功能:
1. 发现本地/远程 Hermes 实例
2. 将 meshctx 端点暴露为 Hermes 可调用的工具
3. 事件桥接: meshctx EventBus ↔ Hermes Hub
4. 统一健康监控
5. 共享配置和密钥

Hermes Hub 消息格式:
  ~/.hermes/.hub_inbox — 全局收件箱 (所有profile共享)
  ~/.hermes/profiles/<profile>/.hub_inbox — profile私有收件箱
"""
import asyncio
import json, os, re, time, socket
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from .kernel import Event, EventPriority, Plugin, PluginInfo, PluginState
except ImportError:
    from src.core.kernel import Event, EventPriority, Plugin, PluginInfo, PluginState

logger = logging.getLogger("meshctx.hermes_connector")


# ═══════════════════════════════════════════════════════
# Hermes Hub Bridge
# ═══════════════════════════════════════════════════════

HERMES_HOME = Path.home() / ".hermes"
GLOBAL_INBOX = HERMES_HOME / ".hub_inbox"
INBOX_SAFE_DIR = HERMES_HOME / ".inbox_safe"  # v5 listener writes here


@dataclass
class HermesInstance:
    """发现的 Hermes 实例"""
    profile: str
    pid: Optional[int] = None
    status: str = "unknown"  # online/offline/busy
    last_heartbeat: float = 0.0
    connected_channels: List[str] = field(default_factory=list)
    skills_count: int = 0
    memory_usage_pct: float = 0.0


class HermesDiscovery:
    """发现和追踪 Hermes 集群实例"""

    def __init__(self):
        self._instances: Dict[str, HermesInstance] = {}
        self._last_scan = 0.0

    async def scan(self) -> Dict[str, HermesInstance]:
        """扫描本地 Hermes 实例"""
        now = time.time()
        if now - self._last_scan < 5:
            return self._instances

        self._last_scan = now

        profiles_dir = HERMES_HOME / "profiles"
        if profiles_dir.exists():
            for pdir in profiles_dir.iterdir():
                if pdir.is_dir() and not pdir.name.startswith(".") and not pdir.name.startswith("_"):
                    instance = HermesInstance(profile=pdir.name)
                    instance.last_heartbeat = now

                    # 检查 AGENTS.md（表示 profile 已配置）
                    agents_md = pdir / "AGENTS.md"
                    if agents_md.exists():
                        instance.status = "configured"

                    # 检查 auth.json（表示实例已激活）
                    auth_file = pdir / "auth.json"
                    if auth_file.exists():
                        try:
                            # auth.json 存在 = 实例已初始化
                            if instance.status == "configured":
                                instance.status = "online"
                            try:
                                auth_content = auth_file.read_text()
                                if len(auth_content) > 100:
                                    instance.status = "online"
                            except Exception:
                                pass
                        except Exception:
                            pass

                    # 检查 skills 目录
                    skills_dir = pdir / "skills"
                    if skills_dir.exists() and skills_dir.is_dir():
                        instance.skills_count = len([f for f in skills_dir.iterdir()
                                                     if f.is_dir() and not f.name.startswith(".")])

                    # 检查 PID 文件
                    pid_file = pdir / ".pid"
                    if pid_file.exists():
                        try:
                            instance.pid = int(pid_file.read_text().strip())
                            if instance.status == "configured":
                                instance.status = "online"
                        except Exception:
                            pass

                    # 检查 .hermes_history（最近活动）
                    history = pdir / ".hermes_history"
                    if history.exists():
                        try:
                            mtime = history.stat().st_mtime
                            if now - mtime < 3600:  # 一小时内活跃
                                instance.status = "online"
                        except Exception:
                            pass

                    self._instances[pdir.name] = instance

        return self._instances

    def get_all(self) -> List[HermesInstance]:
        return list(self._instances.values())

    def get(self, profile: str) -> Optional[HermesInstance]:
        return self._instances.get(profile)


# ═══════════════════════════════════════════════════════
# Event Bridge — meshctx Bus ↔ Hermes Hub
# ═══════════════════════════════════════════════════════

class EventBridge:
    """meshctx 事件总线 ↔ Hermes Hub 消息系统"""

    def __init__(self):
        self._meshctx_to_hermes: List[Dict] = []
        self._hermes_to_meshctx: List[Dict] = []
        self._watch_task: Optional[asyncio.Task] = None

    def register_forward_rule(self, event_type: str, target_profiles: List[str]):
        """将 meshctx 事件转发到指定 Hermes profiles"""
        self._meshctx_to_hermes.append({
            "event_type": event_type,
            "targets": target_profiles,
        })

    def register_receive_rule(self, hub_pattern: str, meshctx_event: str):
        """从 Hermes Hub 消息生成 meshctx 事件"""
        self._hermes_to_meshctx.append({
            "hub_pattern": hub_pattern,
            "meshctx_event": meshctx_event,
        })

    async def forward_to_hermes(self, event: Event):
        """将 meshctx 事件写入 Hermes Hub inbox"""
        for rule in self._meshctx_to_hermes:
            if event.type == rule["event_type"]:
                hub_msg = {
                    "source": "meshctx",
                    "event_type": event.type,
                    "data": event.data,
                    "timestamp": time.time(),
                    "priority": str(event.priority) if hasattr(event, "priority") else "normal",
                }
                hub_line = json.dumps(hub_msg, ensure_ascii=False) + "\n"

                # 写入全局 inbox
                try:
                    GLOBAL_INBOX.parent.mkdir(parents=True, exist_ok=True)
                    with open(GLOBAL_INBOX, "a") as f:
                        f.write(hub_line)
                except Exception as e:
                    logger.warning(f"Failed to write to global inbox: {e}")

                # 写入 profile 私有 inbox
                for profile in rule["targets"]:
                    profile_inbox = HERMES_HOME / "profiles" / profile / ".hub_inbox"
                    try:
                        profile_inbox.parent.mkdir(parents=True, exist_ok=True)
                        with open(profile_inbox, "a") as f:
                            f.write(hub_line)
                    except Exception as e:
                        logger.warning(f"Failed to write to {profile} inbox: {e}")

    async def poll_hermes_inbox(self, bus) -> int:
        """轮询 Hermes Hub inbox，转换为 meshctx 事件"""
        count = 0
        inboxes = []  # v2: 不再碰全局inbox，只处理meshctx自己profile的

        my_profile = os.environ.get("HERMES_PROFILE", "meshctx")
        MACHINE_ID = os.environ.get("HUB_MACHINE_ID", socket.gethostname())

        # 扫描 v5 inbox_safe（listener 写入路径）
        # 🔴 铁律：只读 meshctx.json，不碰 machine.json/{MACHINE_ID}.json
        # machine.json 包含所有 profile 的消息，清空会破坏其他 profile 通讯
        if INBOX_SAFE_DIR.exists():
            meshctx_safe = INBOX_SAFE_DIR / f"{my_profile}.json"
            if meshctx_safe.exists():
                inboxes.append(meshctx_safe)

        for inbox_path in inboxes:
            if not inbox_path.exists():
                continue
            try:
                # 读取
                lines = inbox_path.read_text().strip().split("\n")
                kept = []

                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line)
                        # 跳过滤自己发出的消息（不处理，但保留在inbox）
                        if msg.get("source") == "meshctx":
                            kept.append(line)
                            continue

                        # 匹配转发规则
                        matched = False
                        for rule in self._hermes_to_meshctx:
                            if rule["hub_pattern"] in line:
                                event = Event(
                                    type=rule["meshctx_event"],
                                    data=msg.get("data", msg),
                                    source="hermes_hub",
                                )
                                await bus.publish(event)
                                count += 1
                                matched = True
                                break
                        # 🔴 修复(001/admin报告): 未匹配的消息必须保留——
                        # 可能是发给Hermes agent的DM，meshctx无权吃掉
                        if not matched:
                            kept.append(line)
                    except json.JSONDecodeError:
                        # 🔴 修复: 无法解析的行也保留，不丢数据
                        kept.append(line)
                        continue
                # 过滤完成后原子重写inbox：只移除已匹配处理的消息
                # 原子写避免崩溃时丢消息（tmp+rename）
                tmp_path = inbox_path.with_suffix(inbox_path.suffix + ".tmp")
                tmp_path.write_text("\n".join(kept) + "\n" if kept else "")
                os.replace(tmp_path, inbox_path)
            except Exception as e:
                logger.debug(f"Failed to read inbox {inbox_path}: {e}")

        return count

    async def start_watching(self, bus, interval: float = 2.0):
        """启动 inbox 轮询循环"""
        async def _poll_loop():
            while True:
                try:
                    await self.poll_hermes_inbox(bus)
                except Exception as e:
                    logger.error(f"Inbox poll error: {e}")
                await asyncio.sleep(interval)

        self._watch_task = asyncio.create_task(_poll_loop())

    async def stop_watching(self):
        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass


# ═══════════════════════════════════════════════════════
# Hermes Connector Plugin
# ═══════════════════════════════════════════════════════

class HermesConnectorPlugin(Plugin):
    """使 meshctx 发现并与 Hermes Agent 集群协同工作"""

    info = PluginInfo(
        name="hermes_connector",
        version="1.0.0",
        description="Cluster bridge: meshctx ↔ Hermes agents",
        category="integration",
    )

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.discovery = HermesDiscovery()
        self.bridge = EventBridge()
        self._setup_default_rules()

    def _setup_default_rules(self):
        """设置默认事件转发规则"""
        # meshctx 事件 → Hermes Hub
        self.bridge.register_forward_rule("system.health_alert", ["meshctx", "bsc"])
        self.bridge.register_forward_rule("plugin.error", ["meshctx"])
        self.bridge.register_forward_rule("memory.critical", ["meshctx", "bsc"])

        # Hermes Hub 消息 → meshctx 事件
        self.bridge.register_receive_rule("meshctx.command", "hermes.command")
        self.bridge.register_receive_rule("meshctx.query", "hermes.query")
        self.bridge.register_receive_rule("health_check", "hermes.health_check")

    async def on_load(self, kernel) -> bool:
        """插件加载 — 注册事件转发并启动轮询"""
        self.state = PluginState.LOADED

        # 注册事件处理器
        bus = getattr(kernel, "event_bus", None) or getattr(kernel, "bus", None)
        if bus:
            # 订阅需要转发到 Hermes 的事件
            for rule_type in {"system.health_alert", "plugin.error", "memory.critical"}:
                bus.subscribe(rule_type, self.bridge.forward_to_hermes)

            # 启动 Hub inbox 轮询
            await self.bridge.start_watching(bus, interval=3.0)

        # 初始扫描
        await self.discovery.scan()
        logger.info(f"HermesConnector loaded — found {len(self.discovery.get_all())} Hermes profiles")

        self.state = PluginState.ACTIVE
        return True

    async def on_unload(self):
        """插件卸载"""
        await self.bridge.stop_watching()
        self.state = PluginState.UNLOADED

    def get_cluster_status(self) -> Dict[str, Any]:
        """返回 Hermes 集群状态"""
        instances = self.discovery.get_all()
        return {
            "hermes_instances": len(instances),
            "instances": [
                {
                    "profile": i.profile,
                    "status": i.status,
                    "pid": i.pid,
                    "channels": i.connected_channels,
                    "skills": i.skills_count,
                }
                for i in instances
            ],
            "bridge_rules": {
                "forward": len(self.bridge._meshctx_to_hermes),
                "receive": len(self.bridge._hermes_to_meshctx),
            },
        }

    async def send_to_hermes(self, profile: str, event_type: str, data: Dict) -> bool:
        """向指定 Hermes profile 发送消息"""
        hub_msg = {
            "source": "meshctx",
            "target_profile": profile,
            "event_type": event_type,
            "data": data,
            "timestamp": time.time(),
        }

        profile_inbox = HERMES_HOME / "profiles" / profile / ".hub_inbox"
        try:
            profile_inbox.parent.mkdir(parents=True, exist_ok=True)
            with open(profile_inbox, "a") as f:
                f.write(json.dumps(hub_msg, ensure_ascii=False) + "\n")
            return True
        except Exception as e:
            logger.error(f"Failed to send to {profile}: {e}")
            return False
