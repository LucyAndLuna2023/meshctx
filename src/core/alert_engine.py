"""
MeshCtx v3.46 — Autopilot Intelligence (智能告警引擎)

Autopilot发现异常 → 自动根因分析 → 智能修复建议 → 飞书/日志推送
融合: CausalAnalyzer + Autopilot + KnowledgeGraph
"""
import json, time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

LOG_DIR = Path.home() / ".meshctx" / "autopilot"
ALERT_DIR = LOG_DIR / "alerts"
ALERT_DIR.mkdir(parents=True, exist_ok=True)

class Alert:
    def __init__(self, source: str, severity: str, message: str, data: Dict = None):
        self.source = source
        self.severity = severity  # INFO/WARNING/CRITICAL
        self.message = message
        self.data = data or {}
        self.timestamp = datetime.now().isoformat()
        self.alert_id = f"{source}-{int(time.time())}"

class AlertEngine:
    """智能告警引擎"""
    
    def __init__(self):
        self.alerts: List[Alert] = []
        self._load_history()
    
    def _load_history(self):
        f = ALERT_DIR / "history.json"
        if f.exists():
            with open(f) as fp:
                self.alerts = [Alert(**a) for a in json.load(fp)]
    
    def _save(self):
        with open(ALERT_DIR / "history.json", "w") as f:
            json.dump([a.__dict__ for a in self.alerts[-100:]], f, indent=2)
    
    def raise_alert(self, source: str, severity: str, message: str, data: Dict = None) -> Alert:
        alert = Alert(source, severity, message, data)
        self.alerts.append(alert)
        self._save()
        
        # 写入独立告警文件
        alert_file = ALERT_DIR / f"alert_{alert.alert_id}.json"
        with open(alert_file, "w") as f:
            json.dump(alert.__dict__, f, indent=2)
        
        return alert
    
    def analyze_server_down(self) -> List[str]:
        """分析服务宕机根因"""
        suggestions = []
        
        # 检查日志中的错误模式
        import subprocess
        try:
            r = subprocess.run("journalctl -u meshctx --no-pager -n 50 2>&1", 
                             shell=True, capture_output=True, text=True, timeout=10)
            log_text = r.stdout
            
            if "ModuleNotFoundError" in log_text:
                suggestions.append("缺少模块 → pip install 或检查.gitignore封锁")
            if "ImportError" in log_text:
                suggestions.append("导入错误 → 检查__init__.py和模块路径")
            if "Permission denied" in log_text:
                suggestions.append("权限问题 → chmod/chown修复")
            if "Address already in use" in log_text:
                suggestions.append("端口冲突 → 检查占用进程并kill")
            if "out of memory" in log_text.lower():
                suggestions.append("OOM → 增加内存或优化内存使用")
        except:
            suggestions.append("无法读取日志 → 检查journald服务")
        
        if not suggestions:
            suggestions.append("未检测到明显错误模式 → 手动检查服务状态")
        
        return suggestions
    
    def get_recent_alerts(self, hours: int = 24) -> List[Dict]:
        cutoff = time.time() - hours * 3600
        recent = []
        for a in self.alerts:
            try:
                ts = datetime.fromisoformat(a.timestamp).timestamp()
                if ts > cutoff:
                    recent.append(a.__dict__)
            except:
                pass
        return recent
    
    def get_stats(self) -> Dict:
        total = len(self.alerts)
        critical = sum(1 for a in self.alerts if a.severity == "CRITICAL")
        return {
            "total_alerts": total,
            "critical": critical,
            "recent_24h": len(self.get_recent_alerts(24)),
            "sources": list(set(a.source for a in self.alerts[-50:])),
        }

# 单例
_engine: Optional[AlertEngine] = None
def get_alert_engine() -> AlertEngine:
    global _engine
    if _engine is None:
        _engine = AlertEngine()
    return _engine
