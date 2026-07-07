#!/usr/bin/env python3
"""
Hermes Hub Client — 跨机器任务协调 & 状态同步
Connects to Redis on Cloudcone S6 for real-time message passing between
WSL and Laptop Hermes instances.

Redis channels:
  hub:workers     — heartbeat/status from each machine (unified naming, was hub:status/hub:heartbeat)
  hub:task:new    — new task announced
  hub:task:accept — worker accepts task
  hub:task:result — task complete
  hub:sync        — trigger git pull on all machines
  hub:chat        — human-readable messages between machines
  hub:cmd:<id>    — direct command to specific machine

Redis data:
  hub:workers     — hash: worker_id → {hostname, last_heartbeat, status, ...}
  hub:tasks       — hash: task_id → {from, to, action, status, ...}
  hub:logs        — list: recent events (capped at 500)
"""

import redis
import json
import time
import socket
import threading
import os
import sys
from datetime import datetime, timezone
from typing import Optional

# ── Config ──────────────────────────────────────────────
REDIS_HOST = os.environ.get("HUB_REDIS_HOST", "66.154.101.18")
REDIS_PORT = int(os.environ.get("HUB_REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("HUB_REDIS_PASSWORD", "Hm@2026!1ckwd3zx2i")

# Machine identity
MACHINE_ID = os.environ.get("HUB_MACHINE_ID", socket.gethostname())
MACHINE_LABEL = os.environ.get("HUB_MACHINE_LABEL", MACHINE_ID)

# ── Machine Registry ─────────────────────────────────────
REGISTRY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "machines.json")

def _load_registry() -> dict:
    """Load machines.json and auto-identify this machine."""
    try:
        with open(REGISTRY_FILE) as f:
            reg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    hostname = socket.gethostname()
    for mid, info in reg.get("machines", {}).items():
        if info.get("hostname") == hostname:
            return {"mid": mid, "label": info["label"], **info}
    return {}

MACHINE_REG = _load_registry()
# Registry lookup: only auto-identify if MACHINE_ID was NOT explicitly set
# (avoids conflict when multiple machines share the same hostname, e.g. WSL clones)
_ENV_MACHINE_ID = os.environ.get("HUB_MACHINE_ID")
if MACHINE_REG and not _ENV_MACHINE_ID:
    MACHINE_ID = MACHINE_REG.get("mid", MACHINE_ID)
    MACHINE_LABEL = MACHINE_REG.get("label", MACHINE_LABEL)

# ── Machine ID Resolution ────────────────────────────────
_KNOWN_IDS = {"001", "002", "003", "004"}

def resolve_machine_id(raw: str) -> str:
    """Resolve a target identifier (label, hostname, or profile) to a machine ID.
    
    - If raw is a known machine ID (001-004), return it directly.
    - Otherwise query Redis hub:workers to match by label or hostname.
    - Returns the original raw value if no match found (best-effort).
    """
    if raw in _KNOWN_IDS:
        return raw
    try:
        r = get_redis()
        workers = r.hgetall("hub:workers")
        # Try exact match on label or hostname (only known machine IDs)
        for mid, info_json in workers.items():
            if mid not in _KNOWN_IDS:
                continue
            info = json.loads(info_json)
            if info.get("label") == raw or info.get("hostname") == raw:
                return mid
        # Try substring match on label (only known machine IDs)
        for mid, info_json in workers.items():
            if mid not in _KNOWN_IDS:
                continue
            info = json.loads(info_json)
            label = info.get("label", "")
            hostname = info.get("hostname", "")
            if raw.lower() in label.lower() or raw.lower() in hostname.lower():
                return mid
    except Exception:
        pass
    return raw

def drain_orphaned_queues(own_mid: str):
    """Drain messages from orphaned inbox queues (wrong key patterns)
    and move them to the correct machine inbox. Called during listener startup."""
    drained = 0
    try:
        r = get_redis()
        # Find ALL inbox queues
        for key in r.scan_iter("hub:inbox:*"):
            key_str = key.decode() if isinstance(key, bytes) else key
            # Skip our own correct queue
            if key_str == f"hub:inbox:{own_mid}":
                continue
            # Skip profile-specific queues
            if ":" in key_str.replace("hub:inbox:", ""):
                continue
            # Drain orphaned messages
            while True:
                raw = r.rpop(key_str)
                if not raw:
                    break
                try:
                    data = json.loads(raw)
                    # Re-push to correct machine inbox
                    r.lpush(f"hub:inbox:{own_mid}", raw)
                    r.publish(f"hub:inbox:{own_mid}", raw)
                    drained += 1
                except:
                    pass
        # Also drain hub:profile:* queues if target matches us
        for key in r.scan_iter("hub:profile:*"):
            key_str = key.decode() if isinstance(key, bytes) else key
            parts = key_str.split(":") 
            if len(parts) >= 3 and parts[2] == own_mid:
                continue  # already correct
            # If the target machine ID part matches a query, drain it
            while True:
                raw = r.rpop(key_str)
                if not raw:
                    break
                drained += 1
    except Exception:
        pass
    return drained

# ── Connection ──────────────────────────────────────────

def get_redis() -> redis.Redis:
    """Get a Redis connection."""
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True,
        health_check_interval=30,
    )
    r.ping()
    return r


def get_pubsub() -> redis.client.PubSub:
    """Get a PubSub connection listening on relevant channels."""
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True,
        health_check_interval=30,
    )
    ps = r.pubsub()
    ps.subscribe(
        "hub:task:new",
        "hub:task:accept",
        "hub:task:result",
        "hub:sync",
        "hub:chat",
        f"hub:cmd:{MACHINE_ID}",
    )
    return ps


# ── Status / Heartbeat ─────────────────────────────────

def heartbeat():
    """Send a heartbeat with system status."""
    try:
        r = get_redis()
        load = os.getloadavg()
        mem = _get_mem_info()
        info = {
            "machine_id": MACHINE_ID,
            "label": MACHINE_LABEL,
            "hostname": socket.gethostname(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "load_1m": round(load[0], 2),
            "load_5m": round(load[1], 2),
            "load_15m": round(load[2], 2),
            "mem_total_gb": mem["total"],
            "mem_used_gb": mem["used"],
            "mem_pct": mem["pct"],
            "hermes_running": _check_hermes(),
        }
        r.hset("hub:workers", MACHINE_ID, json.dumps(info))
        r.publish("hub:status", json.dumps(info))

        # Log to hub:logs
        entry = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "heartbeat",
            "from": MACHINE_ID,
            "load": info["load_1m"],
        })
        r.lpush("hub:logs", entry)
        r.ltrim("hub:logs", 0, 499)

        return info
    except Exception as e:
        print(f"[hub] heartbeat failed: {e}", file=sys.stderr)
        return None


def get_workers(r: Optional[redis.Redis] = None) -> dict:
    """Get all machine statuses."""
    if r is None:
        r = get_redis()
    raw = r.hgetall("hub:workers")
    return {k: json.loads(v) for k, v in raw.items()}


def get_logs(r: Optional[redis.Redis] = None, count: int = 20) -> list:
    """Get recent event logs."""
    if r is None:
        r = get_redis()
    items = r.lrange("hub:logs", 0, count - 1)
    return [json.loads(x) for x in items]


# ── Task Management ─────────────────────────────────────

def send_task(target_machine: str, action: str, payload: dict = None,
              task_id: str = None) -> str:
    """Send a task to another machine."""
    r = get_redis()
    if task_id is None:
        task_id = f"task_{int(time.time()*1000)}_{MACHINE_ID[:8]}"

    task = {
        "task_id": task_id,
        "from": MACHINE_ID,
        "to": target_machine,
        "action": action,
        "payload": payload or {},
        "status": "pending",
        "created": datetime.now(timezone.utc).isoformat(),
    }
    r.hset("hub:tasks", task_id, json.dumps(task))
    r.publish("hub:task:new", json.dumps(task))

    # Log
    r.lpush("hub:logs", json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "task_sent",
        "task_id": task_id,
        "from": MACHINE_ID,
        "to": target_machine,
        "action": action,
    }))
    r.ltrim("hub:logs", 0, 499)

    return task_id


def accept_task(task_id: str) -> dict:
    """Accept a task assigned to this machine."""
    r = get_redis()
    raw = r.hget("hub:tasks", task_id)
    if not raw:
        return {"error": "task not found"}

    task = json.loads(raw)
    task["status"] = "accepted"
    task["accepted_at"] = datetime.now(timezone.utc).isoformat()
    r.hset("hub:tasks", task_id, json.dumps(task))
    r.publish("hub:task:accept", json.dumps(task))
    return task


def send_result(task_id: str, status: str, output: str = "",
                error: str = "") -> dict:
    """Send task result."""
    r = get_redis()
    raw = r.hget("hub:tasks", task_id)
    if not raw:
        return {"error": "task not found"}

    task = json.loads(raw)
    task["status"] = status  # "done" or "failed"
    task["output"] = output[:5000]  # cap output
    task["error"] = error[:2000]
    task["completed_at"] = datetime.now(timezone.utc).isoformat()
    r.hset("hub:tasks", task_id, json.dumps(task))
    r.publish("hub:task:result", json.dumps(task))

    # Log
    r.lpush("hub:logs", json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "task_result",
        "task_id": task_id,
        "from": MACHINE_ID,
        "status": status,
    }))
    r.ltrim("hub:logs", 0, 499)

    return task


def get_pending_tasks() -> list:
    """Get tasks assigned to this machine that are pending."""
    r = get_redis()
    all_tasks = r.hgetall("hub:tasks")
    mine = []
    for tid, raw in all_tasks.items():
        task = json.loads(raw)
        if task.get("to") == MACHINE_ID and task.get("status") == "pending":
            mine.append(task)
    return mine


def _run_task(task: dict) -> dict:
    """Execute a task and update its status in hub:tasks.
    
    Task format: {task_id, from, to, action, payload, status}
    
    Supported actions:
    - shell: execute payload.command as shell cmd, capture output
    - exec: same as shell (alias)
    - check_*: informational, marked as observed
    - fix_* / sync_*: informational relay task
    
    Returns: {status: "done"|"failed", output: str, completed_at: str}
    """
    task_id = task.get("task_id", "?")
    action = task.get("action", "")
    payload = task.get("payload", {})
    
    # For informational tasks, just mark as done with a note
    if action.startswith(("check_", "sync_", "fix_", "status_", "diagnose", "ssh_")):
        result = send_result(task_id, "done", f"Task '{action}' acknowledged by {MACHINE_ID} listener. Payload: {json.dumps(payload)[:500]}")
        return {"status": "done", "output": result.get("output", ""), "completed_at": result.get("completed_at", "")}
    
    # Shell / exec commands
    cmd = payload.get("command") or payload.get("cmd") or payload.get("prompt") or ""
    if not cmd:
        result = send_result(task_id, "failed", f"No command in payload for action '{action}'")
        return {"status": "failed", "output": "No command in payload", "completed_at": result.get("completed_at", "")}
    
    try:
        import subprocess
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        output = (proc.stdout + "\n" + proc.stderr).strip()[:5000]
        if proc.returncode == 0:
            result = send_result(task_id, "done", output)
        else:
            result = send_result(task_id, "failed", output)
        return {"status": result.get("status", "failed"), "output": output, "completed_at": result.get("completed_at", "")}
    except subprocess.TimeoutExpired:
        result = send_result(task_id, "failed", "Command timed out after 60s")
        return {"status": "failed", "output": "Command timed out", "completed_at": result.get("completed_at", "")}
    except Exception as e:
        result = send_result(task_id, "failed", str(e))
        return {"status": "failed", "output": str(e), "completed_at": result.get("completed_at", "")}


def get_all_tasks() -> list:
    """Get all tasks."""
    r = get_redis()
    return [json.loads(v) for v in r.hgetall("hub:tasks").values()]


# ── Sync ────────────────────────────────────────────────

def trigger_sync(triggered_by: str = None):
    """Tell all machines to git pull immediately."""
    r = get_redis()
    msg = {
        "from": triggered_by or MACHINE_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    r.publish("hub:sync", json.dumps(msg))


# ── Chat ────────────────────────────────────────────────

def send_chat(message: str):
    """Send a human-readable message to all machines."""
    r = get_redis()
    msg = {
        "from": MACHINE_ID,
        "label": MACHINE_LABEL,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    r.publish("hub:chat", json.dumps(msg))


# ── Direct Messaging (Inbox) ────────────────────────────

def send_dm(target_mid: str, message: str, from_profile: str = "", to_profile: str = "", reply_channel: str = "") -> str:
    """Send a direct message to a specific machine (or profile) inbox.
    
    If to_profile is set, message is routed to that profile's inbox file.
    If from_profile is set, sender identity includes profile info.
    If reply_channel is set, it's included in the message for feishu-reply routing.
    Returns the message ID.
    """
    import uuid
    # Resolve target identifier to a proper machine ID
    target_mid = resolve_machine_id(target_mid)
    r = get_redis()
    msg_id = str(uuid.uuid4())[:8]
    msg = {
        "msg_id": msg_id,
        "from": MACHINE_ID,
        "from_label": MACHINE_LABEL,
        "from_profile": from_profile,
        "to": target_mid,
        "to_profile": to_profile,
        "reply_channel": reply_channel,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # Push to target's inbox
    r.lpush(f"hub:inbox:{target_mid}", json.dumps(msg))
    # Also publish for real-time listeners
    r.publish(f"hub:inbox:{target_mid}", json.dumps(msg))
    # If to_profile set, also push to profile-specific queue + publish
    if to_profile:
        r.lpush(f"hub:profile:{target_mid}:{to_profile}", json.dumps(msg))
        r.publish(f"hub:profile:{target_mid}:{to_profile}", json.dumps(msg))
    return msg_id


# ── Feishu Reply (Outbox) ──────────────────────────

def feishu_reply(channel: str, reply: str, msg_id: str = "", metadata: dict = None) -> str:
    """Push a reply to the Feishu outbox (relay on 003 picks it up).
    
    Args:
        channel: Feishu message target e.g. "chat:oc_xxx:om_xxx"
        reply: Text reply to send back
        msg_id: Original feishu msg_id for reply threading
        metadata: Extra data (e.g. agent, session info)
    
    Returns: "ok" or error description
    """
    r = get_redis()
    payload = {
        "channel": channel,
        "reply": reply,
        "msg_id": msg_id or "",
        "from_machine": MACHINE_ID,
        "timestamp": time.time(),
        "metadata": metadata or {},
    }
    r.lpush("hub:feishu:outbox", json.dumps(payload, ensure_ascii=False))
    r.publish("hub:feishu:outbox", "new")
    # Trim outbox to 500 max
    r.ltrim("hub:feishu:outbox", 0, 499)
    return "ok"


def get_inbox(count: int = 20) -> list:
    """Get messages from own inbox (newest first)."""
    r = get_redis()
    items = r.lrange(f"hub:inbox:{MACHINE_ID}", 0, count - 1)
    return [json.loads(x) for x in items]


# ── Broadcast (All Machines, with Reply) ──────────────────

def broadcast(message: str, reply_to_mid: str = None, reply_to_profile: str = None) -> dict:
    """Send a command to ALL online machines. Each machine should reply.
    
    Returns: {"broadcast_id": str, "targets": [str, ...], "count": int}
    """
    import uuid
    # Resolve reply-to machine ID
    if reply_to_mid:
        reply_to_mid = resolve_machine_id(reply_to_mid)
    r = get_redis()
    broadcast_id = str(uuid.uuid4())[:8]
    workers = get_workers()
    if not workers:
        return {"broadcast_id": broadcast_id, "targets": [], "count": 0}
    
    targets = list(workers.keys())
    msg = {
        "broadcast_id": broadcast_id,
        "type": "broadcast",
        "from": MACHINE_ID,
        "from_label": MACHINE_LABEL,
        "from_profile": reply_to_profile or "admin",
        "reply_to": reply_to_mid or MACHINE_ID,
        "reply_to_profile": reply_to_profile or "admin",
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    for mid in targets:
        r.lpush(f"hub:inbox:{mid}", json.dumps(msg))
        r.publish(f"hub:inbox:{mid}", json.dumps(msg))
    # Also publish to broadcast channel for real-time listeners
    r.publish("hub:broadcast", json.dumps(msg))
    return {"broadcast_id": broadcast_id, "targets": targets, "count": len(targets)}


def broadcast_reply(original_msg: dict, reply_text: str) -> str:
    """Send a reply to a broadcast message.
    Returns the message ID.
    """
    import uuid
    reply_to = original_msg.get("reply_to", original_msg.get("from"))
    reply_profile = original_msg.get("reply_to_profile", original_msg.get("from_profile", "admin"))
    broadcast_id = original_msg.get("broadcast_id", "?")
    
    r = get_redis()
    msg_id = str(uuid.uuid4())[:8]
    msg = {
        "msg_id": msg_id,
        "from": MACHINE_ID,
        "from_label": MACHINE_LABEL,
        "from_profile": "admin",
        "to": reply_to,
        "to_profile": reply_profile,
        "broadcast_id": broadcast_id,
        "type": "broadcast_reply",
        "message": reply_text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    r.lpush(f"hub:inbox:{reply_to}", json.dumps(msg))
    r.publish(f"hub:inbox:{reply_to}", json.dumps(msg))
    if reply_profile:
        r.lpush(f"hub:profile:{reply_to}:{reply_profile}", json.dumps(msg))
        r.publish(f"hub:profile:{reply_to}:{reply_profile}", json.dumps(msg))
    return msg_id


# ── Ping / Pong (Sync Roundtrip) ────────────────────────

def ping(target_mid: str, timeout: float = 10.0) -> dict:
    """Ping another machine and wait for pong reply.
    
    Returns: {"ok": True, "from": "002", "label": "Laptop-E470", ...}
    or      {"ok": False, "error": "timeout"}
    """
    import uuid
    r = get_redis()
    req_id = str(uuid.uuid4())[:8]
    pong_channel = f"hub:pong:{MACHINE_ID}"

    msg = {
        "req_id": req_id,
        "from": MACHINE_ID,
        "from_label": MACHINE_LABEL,
        "message": "ping",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Subscribe to pong reply BEFORE publishing ping
    ps = r.pubsub()
    ps.subscribe(pong_channel)

    # Publish ping
    r.publish(f"hub:ping:{target_mid}", json.dumps(msg))

    # Wait for pong with matching req_id
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        resp = ps.get_message(timeout=min(remaining, 1.0))
        if resp is None:
            continue
        if resp["type"] != "message":
            continue
        try:
            data = json.loads(resp["data"])
        except json.JSONDecodeError:
            continue
        if data.get("req_id") == req_id:
            ps.close()
            return {"ok": True, **data}
    
    ps.close()
    return {"ok": False, "error": f"timeout after {timeout}s", "req_id": req_id}


def pong(ping_msg: dict) -> dict:
    """Reply to a ping. Called by the receiver."""
    r = get_redis()
    reply = {
        "req_id": ping_msg["req_id"],
        "from": MACHINE_ID,
        "from_label": MACHINE_LABEL,
        "message": "pong",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "load_1m": round(os.getloadavg()[0], 2),
        "mem_pct": _get_mem_info()["pct"],
    }
    r.publish(f"hub:pong:{ping_msg['from']}", json.dumps(reply))
    return reply


# ── Helpers ─────────────────────────────────────────────

def _get_mem_info() -> dict:
    """Get memory info from /proc/meminfo."""
    try:
        with open("/proc/meminfo") as f:
            lines = f.read()
        total = _extract_kb(lines, "MemTotal:")
        avail = _extract_kb(lines, "MemAvailable:")
        total_gb = round(total / 1024**2, 1)
        used_gb = round((total - avail) / 1024**2, 1)
        pct = round((total - avail) / total * 100, 1) if total else 0
        return {"total": total_gb, "used": used_gb, "pct": pct}
    except Exception:
        return {"total": 0, "used": 0, "pct": 0}


def _extract_kb(text: str, key: str) -> int:
    for line in text.split("\n"):
        if line.startswith(key):
            return int(line.split(":")[1].strip().split()[0])
    return 0


def _check_hermes() -> bool:
    """Check if Hermes CLI processes are running."""
    try:
        result = os.popen("pgrep -f 'hermes -p' 2>/dev/null").read().strip()
        return len(result) > 0
    except Exception:
        return False


# ── CLI ─────────────────────────────────────────────────

def _cli():
    """Command-line interface for testing."""
    import argparse
    ap = argparse.ArgumentParser(description="Hermes Hub Client")
    ap.add_argument("action", choices=[
        "heartbeat", "workers", "tasks", "logs", "registry",
        "send-task", "result", "sync", "chat", "send", "inbox", "ping", "broadcast",
        "dm", "group", "task",    # v4: new names, old kept as alias
        "listen", "loop", "feishu-reply",
    ])
    ap.add_argument("--target", "-t", help="Target machine ID")
    ap.add_argument("--action-name", "-a", default="shell", help="Task action name (shell/exec/restart_listener)")
    ap.add_argument("--command", "-c", help="Shell command (shorthand for -a shell -p '{\"command\":\"...\"}')")
    ap.add_argument("--payload", "-p", default="{}", help="Task payload JSON")
    ap.add_argument("--task-id", help="Task ID")
    ap.add_argument("--status", default="done", choices=["done", "failed"])
    ap.add_argument("--output", "-o", default="", help="Task output")
    ap.add_argument("--message", "-m", default="hello from hub", help="Chat message")
    ap.add_argument("--from-profile", "-f", default="", help="Sender profile name")
    ap.add_argument("--to-profile", "-tp", default="", help="Target profile name")
    ap.add_argument("--reply-channel", default="", help="Feishu reply channel (feishu:oc_xxx)")
    ap.add_argument("--reply-text", default="", help="Reply text for feishu-reply")
    ap.add_argument("--reply-msg-id", default="", help="Message ID for feishu-reply")
    ap.add_argument("--wait-ack", action="store_true", default=False,
                    help="Wait up to 5s for delivery ack from target listener")
    ap.add_argument("--interval", "-i", type=int, default=30, help="Heartbeat interval")
    args = ap.parse_args()

    if args.action == "heartbeat":
        info = heartbeat()
        print(json.dumps(info, indent=2))

    elif args.action == "workers":
        workers = get_workers()
        header = f"  {'ID':5s} {'LABEL':20s} {'LOAD':>5s} {'MEM':>5s} {'HERMES':>6s} {'AGE':>10s}"
        print(header)
        print("  " + "-" * 55)
        for wid, info in workers.items():
            age_sec = 0
            if "timestamp" in info:
                ts = datetime.fromisoformat(info["timestamp"])
                age_sec = int((datetime.now(timezone.utc) - ts).total_seconds())
            age_str = f"{age_sec}s ago"
            hermes_str = "✓" if info.get("hermes_running") else "✗"
            print(f"  {wid:5s} {info.get('label', wid):20s} {info.get('load_1m',0):4.1f}  "
                  f"{info.get('mem_pct','?')}%  {hermes_str:>6s} {age_str:>10s}")

    elif args.action == "registry":
        # Show all registered machines (online status from Redis)
        workers = get_workers()
        reg = json.load(open(REGISTRY_FILE)) if os.path.exists(REGISTRY_FILE) else {}
        header = "  ID    LABEL                HOSTNAME                  TYPE     ROLE        STATUS"
        print(header)
        print("  " + "-" * 85)
        for mid, info in reg.get("machines", {}).items():
            online = "● ONLINE" if mid in workers else "○ offline"
            print(f"  {mid:5s} {info['label']:20s} {info['hostname']:24s} "
                  f"{info['type']:8s} {info['role']:10s} {online}")

    elif args.action == "tasks":
        tasks = get_all_tasks()
        for t in tasks:
            print(f"  {t['task_id']} {t['from']}→{t['to']} [{t['status']}] {t['action']}")

    elif args.action == "logs":
        logs = get_logs()
        for entry in logs:
            print(f"  {entry['ts'][:19]} [{entry['type']}] {json.dumps(entry, ensure_ascii=False)[:120]}")

    elif args.action in ("send-task", "task"):
        if args.command:
            # Shorthand: --command "cmd" → action=shell, payload={command: "cmd"}
            payload = {"command": args.command}
            action_name = args.action_name
        else:
            payload = json.loads(args.payload)
            # Auto-detect: if action_name looks like a shell command, wrap it
            known_actions = ("shell", "exec", "cmd", "restart_listener")
            if args.action_name not in known_actions:
                payload = {"command": args.action_name}
                action_name = "shell"
            else:
                action_name = args.action_name
        tid = send_task(args.target, action_name, payload)
        print(f"Task sent: {tid}")

    elif args.action == "result":
        result = send_result(args.task_id, args.status, args.output)
        print(json.dumps(result, indent=2))

    elif args.action == "sync":
        trigger_sync()
        print("Sync triggered")

    elif args.action in ("chat", "group"):
        send_chat(args.message)
        print(f"Chat sent: {args.message}")

    elif args.action in ("send", "dm"):
        if not args.target:
            print("Usage: dm|send -t <machine_id> -m <message> [-f from_profile] [-tp to_profile] [--reply-channel <feishu:oc_xxx>]")
            sys.exit(1)
        # Detect -p/-tp confusion
        if args.payload and args.payload != "{}" and not args.to_profile:
            print("⚠️  -p is for --payload (tasks), NOT profile. Use -tp for --to-profile.")
            print(f"    -p value '{args.payload}' was ignored. Did you mean -tp {args.payload} ?")
        msg_id = send_dm(args.target, args.message, args.from_profile, args.to_profile, args.reply_channel)
        profile_tag = ""
        if args.from_profile:
            profile_tag += f" from:{args.from_profile}"
        if args.to_profile:
            profile_tag += f" →{args.to_profile}"
        if args.reply_channel:
            profile_tag += f" <feishu>"
        ack_status = "?"
        if args.wait_ack:
            import time as _time
            deadline = _time.time() + 5
            ack_key = f"hub:ack:{msg_id}"
            while _time.time() < deadline:
                if get_redis().get(ack_key):
                    ack_status = "✅ delivered"
                    break
                _time.sleep(0.3)
            else:
                ack_status = "⏱️ no ack (5s timeout)"
        print(f"DM {msg_id} → {args.target}{profile_tag}: {args.message}  {ack_status if args.wait_ack else ''}")

    elif args.action == "inbox":
        msgs = get_inbox()
        if not msgs:
            print("  (inbox empty)")
        for m in msgs:
            ts = m["timestamp"][:19]
            print(f"  [{ts}] {m['from']}({m['from_label']}): {m['message']}")

    elif args.action == "ping":
        if not args.target:
            print("Usage: ping -t <machine_id>")
            sys.exit(1)
        print(f"Pinging {args.target}... ", end="", flush=True)
        result = ping(args.target)
        if result["ok"]:
            print(f"pong! from {result.get('from_label', result.get('from'))} "
                  f"(load={result.get('load_1m','?')} mem={result.get('mem_pct','?')}%)")
            print(json.dumps(result, indent=2))
        else:
            print(f"NO RESPONSE ({result['error']})")

    elif args.action == "broadcast":
        result = broadcast(args.message, args.target or None, args.to_profile or None)
        print(f"Broadcast {result['broadcast_id']} -> {result['count']} machines: {', '.join(result['targets'])}")
        print(f"   message: {args.message}")

    elif args.action == "listen":
        # ── P0-4: pidfile mutex ──
        import fcntl
        pidfile_path = os.path.expanduser(f"~/.hermes/.hub_listener_{MACHINE_ID}.pid")
        try:
            pid_fd = os.open(pidfile_path, os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.write(pid_fd, str(os.getpid()).encode())
            os.ftruncate(pid_fd, len(str(os.getpid())))
        except (IOError, OSError):
            # Lock held = another listener is running
            with open(pidfile_path) as f:
                existing_pid = f.read().strip()
            # Verify existing PID is actually alive
            try:
                os.kill(int(existing_pid), 0)
                print(f"[hub] Listener already running (PID={existing_pid}), exiting")
                sys.exit(0)
            except (OSError, ValueError):
                # Stale pidfile, remove and retry
                os.unlink(pidfile_path)
                pid_fd = os.open(pidfile_path, os.O_CREAT | os.O_RDWR, 0o644)
                fcntl.flock(pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                os.write(pid_fd, str(os.getpid()).encode())
        
        # Ensure logs directory exists (silent failure otherwise)
        os.makedirs(os.path.expanduser("~/.hermes/logs"), exist_ok=True)
        print(f"[hub] Listening on machine={MACHINE_ID}...")
        # Drain orphaned queues before starting
        drained = drain_orphaned_queues(MACHINE_ID)
        if drained:
            print(f"[hub] Drained {drained} messages from orphaned queues")
        r = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
            decode_responses=True, socket_connect_timeout=5,
            socket_keepalive=True, health_check_interval=30,
        )
        
        # ── Dedup helper: msg_id seen set with 5min TTL ──
        def _is_dup(msg_id):
            """Check and mark a msg_id as seen. Returns True if duplicate."""
            if not msg_id:
                return False  # no msg_id = can't dedup, allow through
            key = f"hub:dedup:{msg_id}"
            # SET NX EX: returns True if key was set (new), None if already exists (dup)
            return not r.set(key, "1", nx=True, ex=300)
        ps = r.pubsub()
        ps.subscribe(
            "hub:task:new", "hub:task:accept", "hub:task:result",
            "hub:sync", "hub:chat",
            "hub:broadcast",
            f"hub:cmd:{MACHINE_ID}",
            f"hub:ping:{MACHINE_ID}",      # auto-pong
            f"hub:inbox:{MACHINE_ID}",     # direct messages
        )
        # Also subscribe to all profile-specific channels for this machine
        profiles_dir = os.path.expanduser("~/.hermes/profiles")
        local_profiles = []
        if os.path.isdir(profiles_dir):
            for pname in os.listdir(profiles_dir):
                if os.path.isdir(os.path.join(profiles_dir, pname)):
                    local_profiles.append(pname)
                    ps.subscribe(f"hub:profile:{MACHINE_ID}:{pname}")
                    # Also subscribe to bare hub:inbox:{profile} — some senders use this (002/004 added)
                    ps.subscribe(f"hub:inbox:{pname}")
        
        # ── P0-1: Ghost subscriber detection (001 added) ──
        import time as _time
        _time.sleep(0.5)  # let subscriptions settle
        for ch in [f"hub:inbox:{MACHINE_ID}", f"hub:cmd:{MACHINE_ID}"]:
            subs = r.pubsub_numsub(ch)
            sub_count = subs[0][1] if subs else 0
            if sub_count == 0:
                print(f"[hub] Ghost sub detected on {ch}, killing ghost pubsub clients...")
                for client in r.client_list():
                    if client.get('cmd') == 'pubsub':
                        try:
                            r.client_kill(client['id'])
                            print(f"[hub] Killed ghost client {client.get('id','?')[:12]} on {client.get('addr','?')}")
                        except:
                            pass
                # Re-subscribe all channels
                ps.unsubscribe()
                _time.sleep(0.5)
                ps.subscribe(
                    "hub:task:new", "hub:task:accept", "hub:task:result",
                    "hub:sync", "hub:chat", "hub:broadcast",
                    f"hub:cmd:{MACHINE_ID}", f"hub:ping:{MACHINE_ID}",
                    f"hub:inbox:{MACHINE_ID}",
                )
                for pname in local_profiles:
                    ps.subscribe(f"hub:profile:{MACHINE_ID}:{pname}")
                    ps.subscribe(f"hub:inbox:{pname}")
                break  # only run once (fix(hub): P0集合 — pidfile互斥+ghost sub检测+profile通道订阅+命名统一+ack送达确认)
        
        # ── Drain persistent inbox queues ──
        print(f"[hub] Draining persistent inbox queues...")
        drained = 0
        for queue_name, profile_dir in [
            (f"hub:inbox:{MACHINE_ID}", None),
        ] + [(f"hub:profile:{MACHINE_ID}:{p}", os.path.expanduser(f"~/.hermes/profiles/{p}"))
             for p in local_profiles] + [(f"hub:inbox:{p}", os.path.expanduser(f"~/.hermes/profiles/{p}"))
             for p in local_profiles]:
            while True:
                raw = r.rpop(queue_name)
                if not raw:
                    break
                try:
                    data = json.loads(raw)
                    msg_id = data.get("msg_id", data.get("broadcast_id", ""))
                    # _is_dup BEFORE write — prevents double-write with pubsub
                    if _is_dup(msg_id):
                        print(f"[drain] DUP {msg_id} — skipping, pubsub beat us")
                        continue
                    # Write to disk
                    machine_inbox = os.path.expanduser("~/.hermes/.hub_inbox")
                    os.makedirs(os.path.dirname(machine_inbox), exist_ok=True)
                    with open(machine_inbox, "a") as f:
                        f.write(json.dumps({**data, "received_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
                        f.flush()
                    # Write to profile inbox — fallback to from_profile if to_profile not set
                    target_profile = data.get("to_profile", "") or data.get("from_profile", "")
                    if target_profile:
                        profile_inbox = os.path.expanduser(f"~/.hermes/profiles/{target_profile}/.hub_inbox")
                        os.makedirs(os.path.dirname(profile_inbox), exist_ok=True)
                        with open(profile_inbox, "a") as f:
                            f.write(json.dumps({**data, "received_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
                            f.flush()
                    drained += 1
                    # _is_dup already called before write above
                except:
                    pass
        if drained:
            print(f"[hub] Drained {drained} queued messages from inbox")
        
        # ── Background periodic poll thread (independent of pub/sub silence) ──
        # Fix P0: hub:tasks and hub:cmd polling must NOT depend on pub/sub silence.
        # Prior design gated polls behind ps.get_message(timeout=N) — with 14 profiles
        # heartbeating, pub/sub never goes silent long enough for timeout to fire,
        # so hub:tasks/hub:cmd stay permanently pending and DMs during listener
        # downtime are never delivered.
        import threading as _threading
        
        def _process_cmd_hash(r_conn, key):
            """Poll hub:cmd HASH entries for this machine."""
            cmd_entries = r_conn.hgetall(key)
            for cmd_key, cmd_raw in cmd_entries.items():
                try:
                    cmd = json.loads(cmd_raw)
                except json.JSONDecodeError:
                    continue
                if cmd.get("machine_id") != MACHINE_ID or cmd.get("status") != "new":
                    # 清理已完成/失败的命令条目，防止内存泄漏 (N0 fix)
                    if cmd.get("status", "new") != "new":
                        r_conn.hdel(key, cmd_key)
                    continue
                _execute_cmd_entry(r_conn, key, cmd_key, cmd)

        def _process_cmd_list(r_conn, key):
            """Poll hub:cmd:{MACHINE_ID} LIST entries — P0 fix for split data structure."""
            import sys
            try:
                llen = r_conn.llen(key)
                print(f"[hub] _process_cmd_list: checking {key} (len={llen}, mid={MACHINE_ID})", flush=True)
                cmd_raw = r_conn.lpop(key)
                while cmd_raw:
                    print(f"[hub] _process_cmd_list: popped from {key}", flush=True)
                    try:
                        cmd = json.loads(cmd_raw)
                    except json.JSONDecodeError as je:
                        print(f"[hub] _process_cmd_list: JSON decode error: {je}, raw={cmd_raw[:100]}", flush=True)
                        cmd_raw = r_conn.lpop(key)
                        continue
                    if cmd.get("machine_id") == MACHINE_ID and cmd.get("status") == "new":
                        print(f"[hub] _process_cmd_list: executing cmd {cmd.get('id')}", flush=True)
                        _execute_cmd_entry(r_conn, key, None, cmd)
                    else:
                        print(f"[hub] _process_cmd_list: SKIP (mid={cmd.get('machine_id')} vs {MACHINE_ID}, status={cmd.get('status')})", flush=True)
                        r_conn.rpush(key, cmd_raw)
                    cmd_raw = r_conn.lpop(key)
            except Exception as e:
                print(f"[hub] Cmd list poll error ({key}): {e}", flush=True)

        def _execute_cmd_entry(r_conn, key, cmd_key, cmd):
            """Execute a single hub:cmd entry and update status."""
            cmd_id = cmd.get("id", cmd_key or "?")
            shell_cmd = cmd.get("command") or cmd.get("cmd") or ""
            if not shell_cmd:
                return
            print(f"[hub] Cmd: {cmd_id} from {cmd.get('from_machine','?')}: {shell_cmd[:80]}")
            cmd["status"] = "processing"
            if cmd_key is not None:
                r_conn.hset(key, cmd_key, json.dumps(cmd))
            import subprocess as _sp
            try:
                proc = _sp.run(shell_cmd, shell=True, capture_output=True, text=True, timeout=60)
                out = (proc.stdout + "\n" + proc.stderr).strip()[:2000]
                cmd["status"] = "done" if proc.returncode == 0 else "failed"
                cmd["output"] = out
            except Exception as exc:
                cmd["status"] = "failed"
                cmd["output"] = str(exc)[:2000]
            cmd["completed_at"] = datetime.now(timezone.utc).isoformat()
            if cmd_key is not None:
                r_conn.hset(key, cmd_key, json.dumps(cmd))
            notif = {
                "type": "cmd_result",
                "cmd_id": cmd_id,
                "status": cmd["status"],
                "output": cmd.get("output", "")[:2000],
                "completed_at": cmd["completed_at"]
            }
            machine_inbox = os.path.expanduser("~/.hermes/.hub_inbox")
            os.makedirs(os.path.dirname(machine_inbox), exist_ok=True)
            with open(machine_inbox, "a") as f:
                f.write(json.dumps(notif, ensure_ascii=False) + "\n")
                f.flush()
        
        def _periodic_poll_loop():
            """Poll hub:tasks + hub:cmd every 60s unconditionally, in background thread."""
            _rr = get_redis()  # own connection for thread safety
            print(f"[poll-thread] Started — will poll every 60s", flush=True)
            while True:
                print(f"[poll-thread] Sleeping 60s...", flush=True)
                time.sleep(60)
                print(f"[poll-thread] Woke up, polling...", flush=True)
                try:
                    # ── Heartbeat (hub:workers) ──
                    heartbeat()
                except Exception as e:
                    print(f"[poll-thread] Heartbeat error: {e}")
                try:
                    # ── P1-1: Cleanup old hub:tasks (keep last 50, remove completed/failed) ──
                    all_tasks = _rr.hgetall("hub:tasks")
                    if len(all_tasks) > 100:
                        completed = [(k, json.loads(v)) for k, v in all_tasks.items()
                                     if json.loads(v).get("status") in ("done", "failed", "completed")]
                        if len(completed) > 50:
                            to_remove = sorted(completed, key=lambda x: x[1].get("completed_at", ""))[:-50]
                            for k, _ in to_remove:
                                _rr.hdel("hub:tasks", k)
                            print(f"[poll-thread] Cleaned {len(to_remove)} old tasks, {len(_rr.hgetall('hub:tasks'))} remaining")
                except Exception as e:
                    print(f"[poll-thread] Tasks cleanup error: {e}")
                try:
                    # ── Poll hub:tasks ──
                    pending = get_pending_tasks()
                    if pending:
                        for task in pending:
                            task_id = task.get("task_id", "?")
                            print(f"[poll-thread] Pending task: {task.get('action')} from {task.get('from')} — {task_id}")
                            task_data = _run_task(task)
                            # 清理已完成任务，防止内存泄漏 (N5 fix)
                            r_conn = get_redis()
                            r_conn.hdel("hub:tasks", task_id)
                            notif = {
                                "type": "task_result",
                                "task_id": task_id,
                                "from": task.get("from"),
                                "from_machine": task.get("from"),
                                "action": task.get("action"),
                                "status": task_data.get("status"),
                                "output": task_data.get("output", "")[:2000],
                                "completed_at": task_data.get("completed_at")
                            }
                            machine_inbox = os.path.expanduser("~/.hermes/.hub_inbox")
                            os.makedirs(os.path.dirname(machine_inbox), exist_ok=True)
                            with open(machine_inbox, "a") as f:
                                f.write(json.dumps(notif, ensure_ascii=False) + "\n")
                                f.flush()
                            payload = task.get("payload", {})
                            if isinstance(payload, str):
                                try:
                                    payload = json.loads(payload)
                                except:
                                    payload = {}
                            if isinstance(payload, dict):
                                target_profile = payload.get("target_profile") or payload.get("profile") or ""
                                if target_profile:
                                    profile_inbox = os.path.expanduser(f"~/.hermes/profiles/{target_profile}/.hub_inbox")
                                    os.makedirs(os.path.dirname(profile_inbox), exist_ok=True)
                                    with open(profile_inbox, "a") as f:
                                        f.write(json.dumps(notif, ensure_ascii=False) + "\n")
                                        f.flush()
                except Exception as e:
                    print(f"[poll-thread] Task poll error: {e}", flush=True)
                try:
                    # ── Poll hub:cmd (HASH) ──
                    _process_cmd_hash(_rr, "hub:cmd")
                    # ── Poll hub:cmd:{MACHINE_ID} (LIST) — P0 fix: commands stored as list items ──
                    _process_cmd_list(_rr, f"hub:cmd:{MACHINE_ID}")
                except Exception as e:
                    print(f"[poll-thread] Cmd poll error: {e}")
                try:
                    # ── Trim alerts/logs to prevent saturation (N3+N4 fix) ──
                    if _rr.llen("hub:alerts") > 100:
                        _rr.ltrim("hub:alerts", -50, -1)
                    if _rr.llen("hub:logs") > 500:
                        _rr.ltrim("hub:logs", -200, -1)
                except Exception:
                    pass
        
        _poll_thread = _threading.Thread(target=_periodic_poll_loop, daemon=True, name="hub-poll")
        _poll_thread.start()
        print(f"[hub] Background poll thread started (60s interval)")
        
        # ── Main listen loop with periodic drain ──
        while True:
            # Use timeout to avoid permanent blocking — enables periodic drain
            msg = ps.get_message(timeout=15)  # short timeout ensures periodic poll runs even with active pub/sub
            if msg is None:
                # Timeout: drain queues to catch any messages missed by pub/sub
                for queue_name, profile_dir in [
                    (f"hub:inbox:{MACHINE_ID}", None),
                ] + [(f"hub:profile:{MACHINE_ID}:{p}", os.path.expanduser(f"~/.hermes/profiles/{p}"))
                     for p in local_profiles] + [(f"hub:inbox:{p}", os.path.expanduser(f"~/.hermes/profiles/{p}"))
                     for p in local_profiles]:
                    drained = 0
                    while True:
                        raw = r.rpop(queue_name)
                        if not raw:
                            break
                        try:
                            data = json.loads(raw)
                            msg_id = data.get("msg_id", data.get("broadcast_id", ""))
                            # _is_dup BEFORE write
                            if _is_dup(msg_id):
                                continue
                            # Write to disk
                            machine_inbox = os.path.expanduser("~/.hermes/.hub_inbox")
                            os.makedirs(os.path.dirname(machine_inbox), exist_ok=True)
                            with open(machine_inbox, "a") as f:
                                f.write(json.dumps({**data, "received_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
                                f.flush()
                            # Write to profile inbox if applicable
                            to_profile = data.get("to_profile", "")
                            if to_profile:
                                profile_inbox = os.path.expanduser(f"~/.hermes/profiles/{to_profile}/.hub_inbox")
                                os.makedirs(os.path.dirname(profile_inbox), exist_ok=True)
                                with open(profile_inbox, "a") as f:
                                    f.write(json.dumps({**data, "received_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
                                    f.flush()
                            drained += 1
                            # _is_dup already called before write above
                        except:
                            pass
                    if drained:
                        print(f"[hub] Periodic drain: {drained} messages from {queue_name}")
                # ── Periodic poll: hub:tasks (tasks may be written without pubsub notify) ──
                try:
                    pending = get_pending_tasks()
                    if pending:
                        for task in pending:
                            task_id = task.get("task_id", "?")
                            print(f"[hub] Polled pending task: {task.get('action')} from {task.get('from')} — {task_id}")
                            task_data = _run_task(task)
                            # Write result to inbox
                            notif = {
                                "type": "task_result",
                                "task_id": task_id,
                                "from": task.get("from"),
                                "from_machine": task.get("from"),
                                "action": task.get("action"),
                                "status": task_data.get("status"),
                                "output": task_data.get("output", "")[:2000],
                                "completed_at": task_data.get("completed_at")
                            }
                            machine_inbox = os.path.expanduser("~/.hermes/.hub_inbox")
                            os.makedirs(os.path.dirname(machine_inbox), exist_ok=True)
                            with open(machine_inbox, "a") as f:
                                f.write(json.dumps(notif, ensure_ascii=False) + "\n")
                                f.flush()
                            payload = task.get("payload", {})
                            if isinstance(payload, str):
                                try:
                                    payload = json.loads(payload)
                                except:
                                    payload = {}
                            if isinstance(payload, dict):
                                target_profile = payload.get("target_profile") or payload.get("profile") or ""
                                if target_profile:
                                    profile_inbox = os.path.expanduser(f"~/.hermes/profiles/{target_profile}/.hub_inbox")
                                    os.makedirs(os.path.dirname(profile_inbox), exist_ok=True)
                                    with open(profile_inbox, "a") as f:
                                        f.write(json.dumps(notif, ensure_ascii=False) + "\n")
                                        f.flush()
                except Exception as e:
                    print(f"[hub] Task poll error: {e}", flush=True)
                # ── Periodic poll: hub:cmd (commands may be written without pubsub notify) ──
                try:
                    _process_cmd_hash(r, "hub:cmd")
                    _process_cmd_list(r, f"hub:cmd:{MACHINE_ID}")
                except Exception as e:
                    print(f"[hub] Cmd poll error: {e}")
                continue
            if msg["type"] != "message":
                continue
            try:
                data = json.loads(msg["data"])
            except json.JSONDecodeError:
                continue
            ch = msg["channel"]
            # Auto-pong: reply immediately to pings
            if ch == f"hub:ping:{MACHINE_ID}":
                pong(data)
                print(f"[{ch}] ping from {data.get('from_label', data.get('from'))} → auto-pong")
                continue
            # ── Task handlers ──
            if ch == "hub:task:new":
                task_id = data.get("task_id", "")
                to_machine = data.get("to", "")
                action = data.get("action", "")
                print(f"[task] NEW: id={task_id} from={data.get('from')} to={to_machine} action={action}")
                if to_machine == MACHINE_ID and task_id:
                    # Accept the task
                    r = get_redis()
                    data["status"] = "accepted"
                    data["accepted_at"] = datetime.now(timezone.utc).isoformat()
                    r.hset("hub:tasks", task_id, json.dumps(data))
                    r.publish("hub:task:accept", json.dumps({
                        "task_id": task_id, "from": MACHINE_ID,
                        "status": "accepted",
                        "accepted_at": data["accepted_at"]}))
                    print(f"[task] ACCEPTED: {task_id} action={action}")
                    # Execute based on action
                    result = ""
                    try:
                        if action in ("shell", "exec", "cmd"):
                            p = data.get("payload", {})
                            if isinstance(p, str):
                                try:
                                    p = json.loads(p)
                                except:
                                    p = {}
                            if isinstance(p, dict):
                                cmd = p.get("command") or p.get("cmd", "")
                            else:
                                cmd = ""

                            import subprocess
                            proc = subprocess.run(cmd, shell=True, capture_output=True,
                                                  text=True, timeout=60)
                            result = (proc.stdout + "\n" + proc.stderr).strip()
                        elif action == "restart_listener":
                            import subprocess
                            result = subprocess.run(
                                "pkill -f 'hub_client.py listen' 2>/dev/null; sleep 1; "
                                f"nohup {sys.executable} {os.path.expanduser('~/.hermes/scripts/hub_client.py')} listen &",
                                shell=True, capture_output=True, text=True, timeout=30
                            ).stdout.strip()
                            print(f"[task] listener restart result: {result[:200]}")
                        else:
                            result = f"Unknown action: {action}"
                    except Exception as e:
                        result = f"Error: {e}"
                    # Send result
                    data["status"] = "completed"
                    data["result"] = result[:2000]
                    data["completed_at"] = datetime.now(timezone.utc).isoformat()
                    r.hset("hub:tasks", task_id, json.dumps(data))
                    r.publish("hub:task:result", json.dumps({
                        "task_id": task_id, "from": MACHINE_ID,
                        "status": "completed", "result": result[:2000]}))
                    print(f"[task] COMPLETED: {task_id} result={result[:100]}")
                continue
            if ch == "hub:task:accept":
                task_id = data.get("task_id", "")
                print(f"[task] ACCEPT_REPLY: {task_id} accepted by {data.get('from')}")
                continue
            if ch == "hub:task:result":
                task_id = data.get("task_id", "")
                print(f"[task] RESULT: {task_id} from {data.get('from')} status={data.get('status')}")
                continue
            # ── Inbox handler ──
            msg_id = data.get("msg_id", data.get("broadcast_id", ""))
            if msg_id and _is_dup(msg_id):
                continue  # duplicate, already written by drain or earlier pub/sub
            to_profile = data.get("to_profile", "")
            from_profile = data.get("from_profile", "")
            from_label = data.get("from_label", data.get("from"))
            profile_tag = f"[{from_profile}@{from_label}]" if from_profile else f"[{from_label}]"
            print(f"[inbox] {profile_tag}: {data.get('message')}")
            
            # Write to machine-level inbox
            # NOTE: msg_id already dedup-checked at L1137-1139.
            # No second _is_dup() here — it would always return True
            # because L1137 already marked the id as seen.
            msg_id = data.get("msg_id", data.get("broadcast_id", f"pub:{datetime.now(timezone.utc).timestamp()}"))
            notif = {
                "msg_id": msg_id,
                "from": data.get("from"),
                "from_label": data.get("from_label", ""),
                "from_profile": from_profile,
                "to_profile": to_profile,
                "reply_channel": data.get("reply_channel", ""),
                "message": data.get("message"),
                "sent_at": data.get("timestamp", ""),
                "received_at": datetime.now(timezone.utc).isoformat()
            }
            notif_path = os.path.expanduser("~/.hermes/.hub_inbox")
            os.makedirs(os.path.dirname(notif_path), exist_ok=True)
            with open(notif_path, "a") as f:
                f.write(json.dumps(notif, ensure_ascii=False) + "\n")
                f.flush()
            print(f"[debug][inbox-write] wrote {len(json.dumps(notif))} bytes to {notif_path}")
            # P0-5: publish ack that message was delivered
            if msg_id:
                r.publish(f"hub:ack:{msg_id}", json.dumps({"status": "delivered", "received_at": datetime.now(timezone.utc).isoformat()}))
            
            # If to_profile set, also write to profile-specific inbox
            # If not set but from_profile is, infer target profile from sender
            target_profile = data.get("to_profile", "") or data.get("from_profile", "")
            if target_profile:
                profile_inbox = os.path.expanduser(f"~/.hermes/profiles/{target_profile}/.hub_inbox")
                os.makedirs(os.path.dirname(profile_inbox), exist_ok=True)
                with open(profile_inbox, "a") as f:
                    f.write(json.dumps(notif, ensure_ascii=False) + "\n")
                    f.flush()
            continue
            # Profile-specific channel messages
            if ch.startswith(f"hub:profile:{MACHINE_ID}:"):
                profile = ch.split(":")[-1]
                from_label = data.get("from_label", data.get("from"))
                from_profile = data.get("from_profile", "")
                print(f"[profile:{profile}] {from_profile}@{from_label}: {data.get('message')}")
                # Dedup check BEFORE writing anything
                msg_id = data.get("msg_id", data.get("broadcast_id", f"pub:{datetime.now(timezone.utc).timestamp()}"))
                if _is_dup(msg_id):
                    print(f"[profile:{profile}] DUP — skipping write (periodic drain beat us)")
                    continue
                # Write to profile inbox so bridge can pick it up
                notif = {
                    "msg_id": data.get("msg_id", ""),
                    "from": data.get("from"),
                    "from_label": data.get("from_label", data.get("from")),
                    "from_profile": from_profile,
                    "to": MACHINE_ID,
                    "to_profile": data.get("to_profile", profile),
                    "reply_channel": data.get("reply_channel", ""),
                    "message": data.get("message"),
                    "timestamp": data.get("timestamp", ""),
                    "sent_at": data.get("timestamp", ""),
                    "received_at": datetime.now(timezone.utc).isoformat()
                }
                profile_inbox = os.path.expanduser(f"~/.hermes/profiles/{profile}/.hub_inbox")
                os.makedirs(os.path.dirname(profile_inbox), exist_ok=True)
                with open(profile_inbox, "a") as f:
                    f.write(json.dumps(notif, ensure_ascii=False) + "\n")
                    f.flush()
                print(f"[debug][profile-inbox] wrote to {profile_inbox}")
                continue
            if ch == "hub:sync":
                print(f"[sync] triggered by {data.get('triggered_by', '?')}")
                os.system(f"bash {os.path.expanduser('~/.hermes/scripts/sync_hermes.sh')} pull")
                continue
            if ch == f"hub:cmd:{MACHINE_ID}":
                # DEPRECATED: prefer HSET hub:cmd + periodic poll. Will remove in v5.
                print(f"[hub] DEPRECATED pub/sub cmd from {data.get('from', '?')}")
                cmd = data.get("cmd", "")
                origin = data.get("from", "?")
                # Whitelist: 001/003/004 can issue remote commands
                # 002 is excluded — previously killed 004's listener via hub:cmd
                if origin not in ("001", "003", "004"):
                    print(f"[cmd] REJECTED from {origin} (not in cmd whitelist): {cmd}")
                    continue
                print(f"[cmd] from {origin}: {cmd}")
                os.system(f"bash -c {__import__('shlex').quote(cmd)}")
                continue
            if ch == "hub:task:new":
                # Process incoming task notification — fetch from hub:tasks hash
                task_id = data.get("task_id", "")
                if not task_id:
                    continue
                raw = r.hget("hub:tasks", task_id)
                if not raw:
                    continue
                task = json.loads(raw)
                if task.get("to") != MACHINE_ID or task.get("status") != "pending":
                    continue
                print(f"[task] NEW from {task.get('from')}: {task.get('action')} — {task_id}")
                task_data = _run_task(task)
                # Write result to machine inbox for agent pickup
                notif = {
                    "type": "task_result",
                    "task_id": task_id,
                    "from": task.get("from"),
                    "from_machine": task.get("from"),
                    "action": task.get("action"),
                    "status": task_data.get("status"),
                    "output": task_data.get("output", "")[:2000],
                    "completed_at": task_data.get("completed_at")
                }
                machine_inbox = os.path.expanduser("~/.hermes/.hub_inbox")
                os.makedirs(os.path.dirname(machine_inbox), exist_ok=True)
                with open(machine_inbox, "a") as f:
                    f.write(json.dumps(notif, ensure_ascii=False) + "\n")
                    f.flush()
                # Also write to profile inboxes referenced in payload
                payload = task.get("payload", {})
                target_profile = payload.get("target_profile") or payload.get("profile") or ""
                if target_profile:
                    profile_inbox = os.path.expanduser(f"~/.hermes/profiles/{target_profile}/.hub_inbox")
                    os.makedirs(os.path.dirname(profile_inbox), exist_ok=True)
                    with open(profile_inbox, "a") as f:
                        f.write(json.dumps(notif, ensure_ascii=False) + "\n")
                        f.flush()
                continue

            if ch == "hub:broadcast":
                # Global broadcast - write to inbox and auto-reply with status
                broadcast_id = data.get("broadcast_id", "?")
                reply_to = data.get("reply_to", data.get("from"))
                reply_profile = data.get("reply_to_profile", data.get("from_profile", "admin"))
                from_label = data.get("from_label", data.get("from"))
                print(f"[broadcast:{broadcast_id}] from {from_label}: {data.get('message')}")

                # Write to machine-level inbox (always write, then dedup)
                notif = {
                    "type": "broadcast",
                    "broadcast_id": broadcast_id,
                    "from": data.get("from"),
                    "from_label": data.get("from_label", ""),
                    "from_profile": data.get("from_profile", "admin"),
                    "reply_to": reply_to,
                    "reply_to_profile": reply_profile,
                    "message": data.get("message"),
                    "sent_at": data.get("timestamp", ""),
                    "received_at": datetime.now(timezone.utc).isoformat()
                }
                notif_path = os.path.expanduser("~/.hermes/.hub_inbox")
                os.makedirs(os.path.dirname(notif_path), exist_ok=True)
                with open(notif_path, "a") as f:
                    f.write(json.dumps(notif, ensure_ascii=False) + "\n")
                    f.flush()
                # Mark as seen AFTER durable write
                if _is_dup(broadcast_id):
                    continue  # duplicate, already written in drain path
                # ⬇️ Only continue to auto-reply / profile write for non-dup messages
                
                # Write to all profile inboxes
                for pname in ["admin"] + [p for p in os.listdir(profiles_dir) if os.path.isdir(os.path.join(profiles_dir, p)) and p != "admin"]:
                    profile_inbox = os.path.expanduser(f"~/.hermes/profiles/{pname}/.hub_inbox")
                    os.makedirs(os.path.dirname(profile_inbox), exist_ok=True)
                    with open(profile_inbox, "a") as f:
                        f.write(json.dumps(notif, ensure_ascii=False) + "\n")
                
                # Auto-reply with status
                try:
                    load = os.popen("cat /proc/loadavg 2>/dev/null | awk '{print $1}'").read().strip()
                except:
                    load = "?"
                try:
                    pids = os.popen("pgrep -c -f 'hermes.*main' 2>/dev/null || echo 0").read().strip()
                except:
                    pids = "?"
                reply_text = f"Received broadcast {broadcast_id} | {MACHINE_LABEL} ({MACHINE_ID}) | load={load} | hermes_pids={pids}"
                broadcast_reply(data, reply_text)
                continue
            print(f"[{ch}] {json.dumps(data, ensure_ascii=False)[:200]}")

    elif args.action == "loop":
        print(f"[hub] Heartbeat loop every {args.interval}s, machine={MACHINE_ID}...")
        while True:
            heartbeat()
            time.sleep(args.interval)

    elif args.action == "feishu-reply":
        if not args.reply_channel:
            print("ERROR: --reply-channel required for feishu-reply")
            sys.exit(1)
        if not args.reply_text:
            print("ERROR: --reply-text required for feishu-reply")
            sys.exit(1)
        result = feishu_reply(args.reply_channel, args.reply_text, args.reply_msg_id)
        print(f"feishu-reply: {result}")


if __name__ == "__main__":
    _cli()
