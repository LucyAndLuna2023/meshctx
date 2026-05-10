"""
meshctx 配置热加载引擎 v1.0
对标 Hermes: 修改 meshctx.yaml 后自动生效，无需重启
"""
import os, time, logging, threading
from pathlib import Path
from typing import Dict, Any, Callable, Optional

logger = logging.getLogger("meshctx.hotreload")

class ConfigWatcher:
    """配置文件监控器 — 检测变更自动重载"""
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.expanduser("~/.meshctx/config.yaml")
        self.path = Path(config_path)
        self._mtime = 0
        self._callbacks: list = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = 2  # 2秒检测一次
    
    def on_change(self, callback: Callable):
        """注册变更回调"""
        self._callbacks.append(callback)
    
    def start(self):
        """启动监控"""
        if self._running:
            return
        self._mtime = self._get_mtime()
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info(f"配置热加载已启动: {self.path}")
    
    def stop(self):
        self._running = False
    
    def _get_mtime(self) -> float:
        try:
            return self.path.stat().st_mtime if self.path.exists() else 0
        except:
            return 0
    
    def _watch_loop(self):
        while self._running:
            try:
                time.sleep(self._interval)
                current = self._get_mtime()
                if current > self._mtime:
                    self._mtime = current
                    logger.info(f"检测到配置变更: {self.path}")
                    for cb in self._callbacks:
                        try:
                            cb()
                        except Exception as e:
                            logger.error(f"热加载回调失败: {e}")
            except Exception:
                pass


class APIKeyFailover:
    """API Key 故障转移 — 主key挂了自动用备用"""
    
    def __init__(self):
        self._keys: Dict[str, list] = {}  # provider → [key1, key2, ...]
        self._failures: Dict[str, int] = {}  # key → 连续失败次数
        self._blacklist: Dict[str, float] = {}  # key → 冷却截止时间
        self.max_failures = 3
        self.cooldown = 300  # 5分钟冷却
    
    def add_key(self, provider: str, key: str):
        """添加API Key"""
        if provider not in self._keys:
            self._keys[provider] = []
        if key and key not in self._keys[provider]:
            self._keys[provider].append(key)
    
    def get_key(self, provider: str) -> Optional[str]:
        """获取可用的API Key (跳过黑名单)"""
        now = time.time()
        keys = self._keys.get(provider, [])
        for key in keys:
            if key in self._blacklist and now < self._blacklist[key]:
                continue
            return key
        return None
    
    def report_failure(self, provider: str, key: str):
        """报告失败"""
        self._failures[key] = self._failures.get(key, 0) + 1
        if self._failures[key] >= self.max_failures:
            self._blacklist[key] = time.time() + self.cooldown
            logger.warning(f"API Key [{key[:8]}...] 已熔断 {self.cooldown}秒")
    
    def report_success(self, key: str):
        """报告成功"""
        self._failures[key] = 0
        self._blacklist.pop(key, None)
    
    def status(self) -> Dict:
        return {
            "providers": {p: len(ks) for p, ks in self._keys.items()},
            "blacklisted": len(self._blacklist),
            "failures": dict(self._failures),
        }


class MemoryBackup:
    """记忆自动备份 — 定期备份+手动恢复"""
    
    def __init__(self, backup_dir: str = None):
        if backup_dir is None:
            backup_dir = os.path.expanduser("~/.meshctx/backups/")
        self.dir = Path(backup_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.max_backups = 10
    
    def backup(self, data: Dict, label: str = "") -> str:
        """备份数据,返回备份文件名"""
        import json
        ts = time.strftime("%Y%m%d_%H%M%S")
        name = f"backup_{ts}_{label}.json" if label else f"backup_{ts}.json"
        path = self.dir / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        
        # 清理旧备份
        backups = sorted(self.dir.glob("backup_*.json"), key=lambda p: p.stat().st_mtime)
        while len(backups) > self.max_backups:
            backups[0].unlink()
            backups.pop(0)
        
        logger.info(f"记忆备份: {name}")
        return str(path)
    
    def restore(self, name: str = None) -> Optional[Dict]:
        """恢复最新的备份,或指定备份名"""
        import json
        backups = sorted(self.dir.glob("backup_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if name:
            path = self.dir / name
        elif backups:
            path = backups[0]
        else:
            return None
        
        if path.exists():
            return json.loads(path.read_text())
        return None
    
    def list_backups(self) -> list:
        return [{"name": p.name, "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)),
                 "size": p.stat().st_size} for p in sorted(self.dir.glob("backup_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)]
