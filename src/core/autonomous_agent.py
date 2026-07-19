"""Autonomous Agent — OODA Loop (Observe-Orient-Decide-Act)

v3.115.20: Proactive monitoring agent that runs in background,
observes system health / API status / git changes / hub messages,
and pushes alerts to Feishu/Lark without waiting for user prompts.

Architecture:
  Every N seconds (default 60):
    OBSERVE  → gather telemetry
    ORIENT   → categorize findings (CRITICAL/WARNING/INFO)
    DECIDE   → deduplicate, throttle, prioritize
    ACT      → push Feishu alert or log-only

Config (in config.yaml or env):
  autonomous_agent:
    enabled: true
    interval_sec: 60
    feishu_webhook: "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
    feishu_secret: ""
    alerts:
      cpu_threshold: 80       # %  → WARNING
      mem_threshold: 85       # %  → WARNING
      disk_threshold: 90      # %  → CRITICAL
      git_check: true
      hub_check: true
      api_health: true
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("meshctx.autonomous")

# ── Alert dedup: don't spam same alert every cycle ──
_ALERT_COOLDOWN = {
    "critical": 180,   # 3 min between repeats
    "warning": 600,    # 10 min
    "info": 1800,      # 30 min
}
_last_alert: dict = {}   # key → timestamp


def _should_alert(key: str, level: str) -> bool:
    """Check if enough time has passed since last alert of this key."""
    now = time.time()
    cooldown = _ALERT_COOLDOWN.get(level, 600)
    if key in _last_alert and (now - _last_alert[key]) < cooldown:
        return False
    _last_alert[key] = now
    return True


# ── Observation helpers ──


async def _check_system_health(cfg: dict) -> list[dict]:
    """Check CPU / memory / disk. Returns list of alert dicts."""
    alerts = []
    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        return [{"level": "warning", "key": "sys:psutil",
                 "title": "psutil 未安装", "body": "无法监控系统资源。pip install psutil"}]

    # Non-blocking: get cpu_percent without interval, use last reading
    cpu = psutil.cpu_percent(interval=None) or 0
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent

    cpu_th = cfg.get("cpu_threshold", 80)
    mem_th = cfg.get("mem_threshold", 85)
    disk_th = cfg.get("disk_threshold", 90)

    if cpu > cpu_th:
        alerts.append({
            "level": "critical" if cpu > 95 else "warning",
            "key": "sys:cpu",
            "title": f"CPU 使用率 {cpu:.0f}%",
            "body": f"阈值: {cpu_th}%，当前: {cpu:.1f}%",
        })
    if mem > mem_th:
        alerts.append({
            "level": "critical" if mem > 95 else "warning",
            "key": "sys:mem",
            "title": f"内存使用率 {mem:.0f}%",
            "body": f"阈值: {mem_th}%，当前: {mem:.1f}%  |  "
                   f"已用 {psutil.virtual_memory().used // (1024**3)}G / "
                   f"总量 {psutil.virtual_memory().total // (1024**3)}G",
        })
    if disk > disk_th:
        alerts.append({
            "level": "critical",
            "key": "sys:disk",
            "title": f"磁盘使用率 {disk:.0f}%",
            "body": f"阈值: {disk_th}%，当前: {disk:.1f}%  |  "
                   f"可用 {psutil.disk_usage('/').free // (1024**3)}G",
        })
    return alerts


async def _check_api_health(cfg: dict) -> list[dict]:
    """Ping local API health endpoint (non-blocking)."""
    port = os.environ.get("MESHCTX_PORT", "3001")
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-sf", "-m", "5", url,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=6)
        if proc.returncode == 0:
            return []
    except Exception:
        pass
    return [{
        "level": "critical",
        "key": "api:health",
        "title": "meshctx API 健康检查失败",
        "body": f"无法访问 {url}，服务可能已挂。",
    }]


async def _check_git(cfg: dict) -> list[dict]:
    """Check git repo: uncommitted changes, behind remote."""
    workdir = cfg.get("repo_path", str(Path.home() / ".meshctx"))
    if not Path(workdir).exists():
        return []
    try:
        # Uncommitted changes
        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=workdir,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        dirty = stdout.decode().strip()

        # Behind remote
        proc2 = await asyncio.create_subprocess_exec(
            "git", "rev-list", "--count", "HEAD..@{upstream}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=workdir,
        )
        stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=10)
        behind = stdout2.decode().strip()

        alerts = []
        if dirty:
            files = [l.split()[-1] for l in dirty.split("\n")[:5]]
            alerts.append({
                "level": "warning",
                "key": "git:dirty",
                "title": f"Git 有未提交修改 ({len(dirty.split(chr(10)))} 文件)",
                "body": f"文件: {', '.join(files)}...",
            })
        if behind and behind.isdigit() and int(behind) > 0:
            alerts.append({
                "level": "info",
                "key": "git:behind",
                "title": f"Git 落后远程 {behind} 个 commit",
                "body": f"建议 git pull 同步。",
            })
        return alerts
    except Exception:
        return []


async def _check_hub_inbox(cfg: dict) -> list[dict]:
    """Check for new messages from other agents in hub inbox."""
    inbox_path = Path.home() / ".hermes" / ".hub_inbox"
    # Also check profile inbox
    profile_inbox = Path.home() / ".hermes" / "profiles" / "meshctx" / ".hub_inbox"

    all_msgs = []
    for path in (inbox_path, profile_inbox):
        if not path.exists():
            continue
        try:
            for line in path.read_text().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    all_msgs.append(msg)
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass

    if not all_msgs:
        return []

    # Only report new messages in last cycle
    now = time.time()
    recent = [
        m for m in all_msgs
        if m.get("from") and m.get("from") != "meshctx"
        and (now - _parse_ts(m.get("sent_at") or m.get("timestamp") or "")) < 120
    ]
    if not recent:
        return []

    senders = list(set(m["from"] for m in recent))
    return [{
        "level": "info",
        "key": "hub:inbox",
        "title": f"Hub 新消息来自: {', '.join(senders)}",
        "body": f"共 {len(recent)} 条消息。回复请用 hub_client.py send。",
    }]


def _parse_ts(ts_str: str) -> float:
    """Parse ISO timestamp to epoch."""
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0


# ── Main OODA loop ──


class AutonomousAgent:
    """OODA-based autonomous monitoring agent."""

    def __init__(self, config: dict | None = None):
        self.config = config or _load_autonomous_config()
        self._enabled = self.config.get("enabled", True)
        self._interval = self.config.get("interval_sec", 60)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self._total_alerts = 0
        self._notifier = None

    # ── Public API ──

    async def start(self):
        """Start the OODA loop as a background task."""
        if not self._enabled:
            logger.info("AutonomousAgent: disabled in config, skipping")
            return

        webhook = self.config.get("feishu_webhook", "")
        secret = self.config.get("feishu_secret", "")
        if webhook:
            from .feishu_notify import FeishuNotifier
            self._notifier = FeishuNotifier(webhook, secret)
            logger.info(f"AutonomousAgent: Feishu webhook configured")
        else:
            logger.info("AutonomousAgent: no webhook, alerts will be log-only")

        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            f"AutonomousAgent started (interval={self._interval}s, "
            f"webhook={'yes' if webhook else 'no'})"
        )

    async def stop(self):
        """Stop the OODA loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AutonomousAgent stopped")

    def status(self) -> dict:
        return {
            "running": self._running,
            "enabled": self._enabled,
            "interval_sec": self._interval,
            "cycle_count": self._cycle_count,
            "total_alerts": self._total_alerts,
            "webhook_configured": bool(self._notifier),
        }

    # ── OODA Core ──

    async def _loop(self):
        """Main OODA loop."""
        # Warm-up: first observation after 10s
        await asyncio.sleep(10)

        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"AutonomousAgent tick error: {e}")
            self._cycle_count += 1
            await asyncio.sleep(self._interval)

    async def _tick(self):
        """One OODA cycle: Observe → Orient → Decide → Act."""
        cfg = self.config.get("alerts", {})

        # ── OBSERVE ──
        observations = []
        if cfg.get("cpu_threshold") is not None or True:  # always check
            observations += await _check_system_health(cfg)
        if cfg.get("api_health", True):
            observations += await _check_api_health(cfg)
        if cfg.get("git_check", True):
            observations += await _check_git(cfg)
        if cfg.get("hub_check", True):
            observations += await _check_hub_inbox(cfg)

        # ── ORIENT + DECIDE: dedup & filter ──
        actionable = []
        for obs in observations:
            key = obs.get("key", obs.get("title", ""))
            level = obs.get("level", "info")
            if _should_alert(key, level):
                actionable.append(obs)

        if not actionable:
            return

        logger.debug(f"AutonomousAgent: {len(actionable)} actionable alerts (of {len(observations)} total)")

        # ── ACT ──
        for alert in actionable:
            level = alert["level"]
            title = alert["title"]
            body = alert["body"]

            # Always log
            log_fn = {"critical": logger.error, "warning": logger.warning, "info": logger.info}.get(level, logger.info)
            log_fn(f"[{level.upper()}] {title}: {body}")

            # Push to Feishu if configured
            if self._notifier:
                try:
                    self._notifier.send_alert(level, title, body)
                    self._total_alerts += 1
                except Exception as e:
                    logger.warning(f"Feishu push failed: {e}")
            else:
                self._total_alerts += 1  # count log-only alerts too

    # ── Manual trigger ──

    async def observe_now(self) -> list[dict]:
        """Run one observation pass manually (for API endpoint)."""
        cfg = self.config.get("alerts", {})
        observations = []
        observations += await _check_system_health(cfg)
        observations += await _check_api_health(cfg)
        observations += await _check_git(cfg)
        observations += await _check_hub_inbox(cfg)
        return observations


# ── Config ──


def _load_autonomous_config() -> dict:
    """Load autonomous agent config from config.yaml or env."""
    cfg = {
        "enabled": True,
        "interval_sec": int(os.environ.get("AUTONOMOUS_INTERVAL", "60")),
        "feishu_webhook": os.environ.get("FEISHU_WEBHOOK_URL", ""),
        "feishu_secret": os.environ.get("FEISHU_WEBHOOK_SECRET", ""),
        "repo_path": str(Path.home() / ".meshctx"),
        "alerts": {
            "cpu_threshold": int(os.environ.get("ALERT_CPU_THRESHOLD", "80")),
            "mem_threshold": int(os.environ.get("ALERT_MEM_THRESHOLD", "85")),
            "disk_threshold": int(os.environ.get("ALERT_DISK_THRESHOLD", "90")),
            "git_check": os.environ.get("ALERT_GIT_CHECK", "1") == "1",
            "hub_check": os.environ.get("ALERT_HUB_CHECK", "1") == "1",
            "api_health": os.environ.get("ALERT_API_HEALTH", "1") == "1",
        },
    }

    # Try config.yaml override
    config_path = Path.home() / ".meshctx" / "config.yaml"
    if config_path.exists():
        try:
            import yaml  # type: ignore[import-untyped]
            with open(config_path) as f:
                yaml_cfg = yaml.safe_load(f) or {}
            ac = yaml_cfg.get("autonomous_agent", {})
            if ac:
                cfg.update({k: v for k, v in ac.items() if k != "alerts"})
                cfg["alerts"].update(ac.get("alerts", {}))
        except Exception as e:
            logger.debug(f"Config load skipped: {e}")

    return cfg


# ── Singleton ──

_agent: Optional[AutonomousAgent] = None


def get_autonomous_agent() -> AutonomousAgent:
    """Get or create the singleton AutonomousAgent."""
    global _agent
    if _agent is None:
        _agent = AutonomousAgent()
    return _agent
