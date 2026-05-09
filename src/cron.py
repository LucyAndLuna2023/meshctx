"""
meshctx Cron 定时调度引擎
支持标准 crontab 语法 + 秒级精度
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Coroutine, Dict, List, Optional
from datetime import datetime

try:
    from .kernel import Event, EventPriority, Plugin, PluginInfo
except ImportError:
    from src.core.kernel import Event, EventPriority, Plugin, PluginInfo

logger = logging.getLogger("meshctx.cron")


@dataclass
class CronJob:
    """定时任务"""
    name: str
    schedule: str            # crontab: "*/5 * * * *" 或 "every 30m"
    action: str              # 事件类型 或 描述
    data: Dict = field(default_factory=dict)
    enabled: bool = True
    last_run: Optional[float] = None
    run_count: int = 0
    created_at: float = field(default_factory=time.time)


class CronParser:
    """
    解析 crontab 和人类可读的时间表达式
    
    支持:
        "*/5 * * * *"     # 每5分钟
        "0 9 * * 1-5"     # 工作日9点
        "every 30m"       # 每30分钟
        "every 1h"        # 每小时
        "every 6h"        # 每6小时(每天4次)
        "daily at 9:00"   # 每天9点
        "weekly mon 9:00" # 每周一9点
    """
    
    @staticmethod
    def parse(expr: str) -> Callable[[float], bool]:
        """返回函数: 给定时间戳是否应该触发"""
        
        # 人类可读表达式
        if expr.startswith("every "):
            return CronParser._parse_every(expr)
        
        if expr.startswith("daily"):
            return CronParser._parse_daily(expr)
        
        if expr.startswith("weekly"):
            return CronParser._parse_weekly(expr)
        
        # 标准 crontab: 分 时 日 月 周
        return CronParser._parse_crontab(expr)
    
    @staticmethod
    def _parse_crontab(expr: str) -> Callable[[float, float], bool]:
        """解析标准 crontab 表达式"""
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"无效 crontab: {expr}")
        
        def _match(value: str, current: int) -> bool:
            if value == "*":
                return True
            if value.startswith("*/"):
                interval = int(value[2:])
                return current % interval == 0
            if "," in value:
                return current in [int(v) for v in value.split(",")]
            if "-" in value:
                start, end = value.split("-")
                return int(start) <= current <= int(end)
            return int(value) == current
        
        def checker(last_run: float) -> bool:
            now = datetime.now()
            return all([
                _match(parts[0], now.minute),
                _match(parts[1], now.hour),
                _match(parts[2], now.day),
                _match(parts[3], now.month),
                _match(parts[4], now.weekday()),
            ])
        
        return checker
    
    @staticmethod
    def _parse_every(expr: str) -> Callable[[float, float], bool]:
        """解析 'every Xm' 或 'every Xh'"""
        import re
        m = re.match(r'every\s+(\d+)\s*(m|min|h|hour|s|sec)', expr)
        if not m:
            raise ValueError(f"无效表达式: {expr}")
        
        value = int(m.group(1))
        unit = m.group(2)[0]
        
        if unit == 's':
            interval = value
        elif unit == 'm':
            interval = value * 60
        elif unit == 'h':
            interval = value * 3600
        else:
            interval = value * 60
        
        def checker(last_run: float) -> bool:
            if last_run is None:
                return True
            return (time.time() - last_run) >= interval
        
        return checker
    
    @staticmethod
    def _parse_daily(expr: str) -> Callable[[float, float], bool]:
        """解析 'daily at 9:00'"""
        import re
        m = re.search(r'(\d+):(\d+)', expr)
        hour, minute = int(m.group(1)), int(m.group(2)) if m else (0, 0)
        
        def checker(last_run: float) -> bool:
            now = datetime.now()
            if last_run and time.time() - last_run < 3600:
                return False
            return now.hour == hour and now.minute == minute
        
        return checker
    
    @staticmethod
    def _parse_weekly(expr: str) -> Callable[[float, float], bool]:
        """解析 'weekly mon 9:00'"""
        import re
        days = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}
        m = re.search(r'(\w+)\s+(\d+):(\d+)', expr)
        if not m:
            raise ValueError(f"无效表达式: {expr}")
        
        day = m.group(1)[:3].lower()
        day_num = days.get(day, 0)
        hour, minute = int(m.group(2)), int(m.group(3))
        
        def checker(last_run: float) -> bool:
            now = datetime.now()
            if last_run and time.time() - last_run < 3600:
                return False
            return now.weekday() == day_num and now.hour == hour and now.minute == minute
        
        return checker


class CronPlugin(Plugin):
    """
    Cron 定时调度插件
    
    用法:
        # config.yaml
        cron:
          jobs:
            - name: "每小时健康检查"
              schedule: "every 1h"
              action: "system.health_check"
            - name: "每日收盘扫描"
              schedule: "0 15 * * 1-5"
              action: "stock.scan"
    """

    info = PluginInfo(
        name="cron",
        version="1.0.0",
        description="Cron 定时调度引擎 — 支持 crontab + 人类可读语法",
        author="meshctx",
    )

    def __init__(self):
        self._jobs: Dict[str, CronJob] = {}
        self._parsers: Dict[str, Callable] = {}
        self._task: Optional[asyncio.Task] = None
        self._tick_interval = 10  # 每10秒检查一次

    async def on_load(self):
        cron_config = self.kernel.config.get("cron", {})
        jobs = cron_config.get("jobs", [])
        
        for job_cfg in jobs:
            self.add_job(
                name=job_cfg["name"],
                schedule=job_cfg["schedule"],
                action=job_cfg.get("action", ""),
                data=job_cfg.get("data", {}),
            )
        
        if self._jobs:
            self._task = asyncio.create_task(self._tick_loop())
        
        logger.info(f"Cron 已加载: {len(self._jobs)} 个任务")

    async def on_unload(self):
        if self._task:
            self._task.cancel()
        logger.info("Cron 已卸载")

    def add_job(self, name: str, schedule: str, action: str = "",
                data: Dict = None):
        """添加定时任务"""
        try:
            parser = CronParser.parse(schedule)
        except ValueError as e:
            logger.error(f"任务 '{name}' 时间表达式无效: {e}")
            return
        
        job = CronJob(
            name=name, schedule=schedule, action=action, data=data or {},
        )
        self._jobs[name] = job
        self._parsers[name] = parser
        logger.info(f"Cron 任务: {name} ({schedule})")

    def remove_job(self, name: str):
        self._jobs.pop(name, None)
        self._parsers.pop(name, None)

    def list_jobs(self) -> List[Dict]:
        return [
            {
                "name": j.name,
                "schedule": j.schedule,
                "enabled": j.enabled,
                "run_count": j.run_count,
                "last_run": (
                    datetime.fromtimestamp(j.last_run).isoformat()
                    if j.last_run else "never"
                ),
            }
            for j in self._jobs.values()
        ]

    async def _tick_loop(self):
        """定时轮询"""
        while True:
            try:
                await self._check_jobs()
                await asyncio.sleep(self._tick_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cron tick error: {e}")
                await asyncio.sleep(30)

    async def _check_jobs(self):
        """检查并触发到期的任务"""
        now = time.time()
        
        for name, job in self._jobs.items():
            if not job.enabled:
                continue
            
            parser = self._parsers.get(name)
            if not parser:
                continue
            
            try:
                should_run = parser(job.last_run)
            except:
                continue
            
            if should_run:
                job.last_run = now
                job.run_count += 1
                
                logger.debug(f"Cron 触发: {name}")
                
                await self.kernel.bus.publish(Event(
                    type=job.action or f"cron.{name}",
                    source="cron",
                    priority=EventPriority.NORMAL,
                    data={
                        "job_name": name,
                        "schedule": job.schedule,
                        "run_count": job.run_count,
                        **job.data,
                    },
                ))
