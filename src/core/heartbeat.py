"""
meshctx Heartbeat — 心跳监控
对标: OpenClaw heartbeat
"""
import time, threading, json, os
from pathlib import Path
from typing import Callable, Optional

HB_DIR = Path(os.environ.get("MESHCTX_STATE_DIR", Path.home() / ".meshctx")) / "heartbeats"
HB_DIR.mkdir(parents=True, exist_ok=True)

_heartbeats: dict[str, dict] = {}
_hb_lock = threading.Lock()

def heartbeat_start(name: str, interval_seconds: int = 60,
                    on_miss: Callable = None, max_misses: int = 3) -> dict:
    """启动心跳监控
    
    Args:
        name: 服务/任务名称
        interval_seconds: 期望心跳间隔
        on_miss: 心跳丢失时的回调
        max_misses: 连续丢失几次触发告警
    """
    hb = {
        "name": name, "interval": interval_seconds,
        "last_beat": time.time(), "misses": 0,
        "max_misses": max_misses, "on_miss": on_miss,
        "running": True, "total_beats": 0
    }
    with _hb_lock:
        _heartbeats[name] = hb
    
    # 后台监控线程
    def _monitor():
        while hb["running"]:
            time.sleep(interval_seconds)
            if not hb["running"]:
                break
            elapsed = time.time() - hb["last_beat"]
            if elapsed > interval_seconds * 1.5:
                hb["misses"] += 1
                if hb["misses"] >= max_misses:
                    # 持久化告警
                    alert = {"name": name, "misses": hb["misses"], 
                             "last_beat": hb["last_beat"], "time": time.time()}
                    (HB_DIR / f"{name}_alert.json").write_text(json.dumps(alert))
                    if on_miss:
                        try:
                            on_miss(name, hb["misses"])
                        except:
                            pass
            else:
                hb["misses"] = 0
    
    t = threading.Thread(target=_monitor, daemon=True)
    t.start()
    hb["_monitor_thread"] = t
    
    return {"ok": True, "name": name, "interval": interval_seconds, "max_misses": max_misses}

def heartbeat_ping(name: str) -> dict:
    """发送心跳 (重置计时器)"""
    with _hb_lock:
        if name not in _heartbeats:
            return {"ok": False, "error": f"Heartbeat {name} not started"}
        _heartbeats[name]["last_beat"] = time.time()
        _heartbeats[name]["total_beats"] += 1
        _heartbeats[name]["misses"] = 0
        # 清除告警
        alert_file = HB_DIR / f"{name}_alert.json"
        if alert_file.exists():
            alert_file.unlink()
    return {"ok": True, "name": name, "beats": _heartbeats[name]["total_beats"]}

def heartbeat_status(name: str = None) -> dict:
    """查看心跳状态"""
    if name:
        if name in _heartbeats:
            hb = _heartbeats[name]
            return {"ok": True, "name": name, 
                    "last_beat": hb["last_beat"],
                    "ago_seconds": round(time.time() - hb["last_beat"], 1),
                    "misses": hb["misses"], "total_beats": hb["total_beats"],
                    "running": hb["running"]}
        return {"ok": False, "error": f"Heartbeat {name} not found"}
    
    all_hb = []
    for n, hb in _heartbeats.items():
        all_hb.append({
            "name": n, "ago_seconds": round(time.time() - hb["last_beat"], 1),
            "misses": hb["misses"], "total_beats": hb["total_beats"],
            "running": hb["running"]
        })
    return {"ok": True, "heartbeats": all_hb}

def heartbeat_stop(name: str) -> dict:
    """停止心跳监控"""
    with _hb_lock:
        if name in _heartbeats:
            _heartbeats[name]["running"] = False
            del _heartbeats[name]
            return {"ok": True, "stopped": name}
    return {"ok": False, "error": f"Heartbeat {name} not found"}
