"""
meshctx Monitor — 后台监控命令输出，检测变化自动反应
对标: Claude Code Monitor tool
"""
import subprocess, threading, time, json, os, re
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field

STATE_DIR = Path(os.environ.get("MESHCTX_STATE_DIR", Path.home() / ".meshctx"))
STATE_DIR.mkdir(parents=True, exist_ok=True)

@dataclass
class MonitorSession:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """监控会话"""
    session_id: str
    command: str
    workdir: str
    watch_patterns: list[str]  # 匹配这些pattern时通知
    process: Optional[subprocess.Popen] = None
    output_lines: list[str] = field(default_factory=list)
    matched_events: list[dict] = field(default_factory=list)
    running: bool = True
    started_at: float = 0.0

_monitors: dict[str, MonitorSession] = {}

def monitor_start(command: str, watch_patterns: list[str] = None, 
                  workdir: str = None, timeout: int = 600) -> str:
    """后台启动监控命令，匹配到pattern时返回事件"""
    import uuid
    sid = f"mon_{uuid.uuid4().hex[:8]}"
    
    session = MonitorSession(
        session_id=sid,
        command=command,
        workdir=workdir or os.getcwd(),
        watch_patterns=watch_patterns or [],
        started_at=time.time()
    )
    
    def _run(**kw):
        try:
            session.process = subprocess.Popen(
                command, shell=True, cwd=session.workdir,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1
            )
            for line in iter(session.process.stdout.readline, ''):
                if not session.running:
                    session.process.terminate()
                    break
                session.output_lines.append(line.rstrip())
                # 检查匹配
                for pat in session.watch_patterns:
                    if re.search(pat, line, re.IGNORECASE):
                        session.matched_events.append({
                            "pattern": pat,
                            "line": line.rstrip(),
                            "time": time.time()
                        })
            session.process.stdout.close()
            session.process.wait()
        except Exception as e:
            session.output_lines.append(f"[ERROR] {e}")
        finally:
            session.running = False
    
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    _monitors[sid] = session
    
    # 等待首次匹配或超时
    deadline = time.time() + min(timeout, 30)
    while time.time() < deadline:
        if session.matched_events:
            break
        if not session.running:
            break
        time.sleep(0.5)
    
    if session.matched_events:
        events = [f"  [{e['pattern']}] {e['line'][:200]}" for e in session.matched_events]
        return f"monitor({sid}) matched:\n" + "\n".join(events)
    elif not session.running:
        recent = "\n".join(session.output_lines[-20:]) if session.output_lines else "(no output)"
        return f"monitor({sid}) exited. Recent output:\n{recent}"
    else:
        recent = "\n".join(session.output_lines[-10:]) if session.output_lines else "(no output yet)"
        return f"monitor({sid}) running, no match yet. Recent:\n{recent}"

def monitor_poll(session_id: str = None) -> str:
    """轮询监控会话状态"""
    if session_id and session_id in _monitors:
        s = _monitors[session_id]
        new_events = s.matched_events.copy()
        s.matched_events.clear()
        status = "running" if s.running else "exited"
        recent = "\n".join(s.output_lines[-15:]) if s.output_lines else ""
        return f"monitor({s.session_id}) [{status}]\nevents={len(new_events)}\n{recent[:2000]}"
    
    # 列出所有
    lines = [f"{'ID':<14} {'STATUS':<8} {'COMMAND':<50} {'MATCHES'}" ]
    for s in _monitors.values():
        lines.append(f"{s.session_id:<14} {'running' if s.running else 'exited':<8} {s.command[:48]:<50} {len(s.matched_events)}")
    return "\n".join(lines) if len(lines)>1 else "no monitors"

def monitor_stop(session_id: str) -> str:
    """停止监控会话"""
    if session_id in _monitors:
        s = _monitors[session_id]
        s.running = False
        if s.process and s.process.poll() is None:
            s.process.terminate()
        del _monitors[session_id]
        return f"monitor({session_id}) stopped"
    return f"monitor({session_id}) not found"

def monitor_log(session_id: str, lines: int = 50) -> str:
    """获取监控会话完整日志"""
    if session_id in _monitors:
        s = _monitors[session_id]
        return f"=== monitor({s.session_id}) log ===\n" + "\n".join(s.output_lines[-lines:])
    return f"monitor({session_id}) not found"
