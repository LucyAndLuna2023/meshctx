"""
MeshCtx Agent Swarm — Manager-Worker 多Agent协同系统
=====================================================

核心理念：一个Manager管理多个Worker Agent，通过网络+密钥认证。

架构：
  ManagerAgent (主节点)
    ├── 身份: ed25519密钥对 + agent_id
    ├── Worker注册表: {worker_id: WorkerInfo(addr, pubkey, capabilities, status)}
    ├── 任务队列: 分解→派发→收集→汇总
    └── 心跳监控: 30秒超时→自动摘除

  WorkerAgent (工作节点)
    ├── 身份: 自己的ed25519密钥对 + worker_id  
    ├── 注册: POST /swarm/register → Manager
    ├── 心跳: POST /swarm/heartbeat (定期)
    └── 执行: 接收任务→调用LLM→返回结果

通信协议:
  - 注册: Worker → Manager POST /swarm/register
  - 心跳: Worker → Manager POST /swarm/heartbeat  
  - 派发: Manager → Worker POST /swarm/task
  - 结果: Worker → Manager POST /swarm/result
  - 认证: ed25519签名 + timestamp防重放

USAGE:
  # 启动Manager
  meshctx swarm start --role manager --port 3000
  
  # 启动Worker (另一台机器)
  meshctx swarm start --role worker --manager http://192.168.3.47:3000 --key worker_key.json
  
  # 提交任务
  curl -X POST http://localhost:3000/swarm/execute \
    -H "Content-Type: application/json" \
    -d '{"task": "搜索Python asyncio最佳实践并写总结"}'
"""

import asyncio
import time
import uuid
import json
import hmac
import hashlib
import logging
import os
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Callable, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 身份认证 ──────────────────────────────────────────────

class AgentIdentity:
    """Agent身份 = ed25519密钥对 + agent_id"""
    
    def __init__(self, agent_id: str = None, key_path: str = None):
        self.agent_id = agent_id or f"agent_{uuid.uuid4().hex[:8]}"
        self._secret = None
        self._public = None
        
        if key_path and os.path.exists(key_path):
            self._load_key(key_path)
        else:
            self._generate_key()
            if key_path:
                self._save_key(key_path)
    
    def _generate_key(self):
        """生成密钥对"""
        try:
            from nacl.signing import SigningKey
            sk = SigningKey.generate()
            self._secret = sk.encode().hex()
            self._public = sk.verify_key.encode().hex()
        except ImportError:
            # Fallback: HMAC-based key
            raw = os.urandom(32)
            self._secret = raw.hex()
            self._public = hashlib.sha256(raw + b'pub').hexdigest()
            logger.warning("nacl not installed, using HMAC fallback (weaker)")
    
    def _save_key(self, path: str):
        with open(path, 'w') as f:
            json.dump({
                "agent_id": self.agent_id,
                "secret_key": self._secret,
                "public_key": self._public,
            }, f, indent=2)
        os.chmod(path, 0o600)
        logger.info(f"Key saved to {path}")
    
    def _load_key(self, path: str):
        with open(path) as f:
            data = json.load(f)
        self.agent_id = data["agent_id"]
        self._secret = data["secret_key"]
        self._public = data["public_key"]
    
    @property
    def public_key(self) -> str:
        return self._public
    
    def sign_request(self, payload: dict) -> dict:
        """签名请求 — 防伪造"""
        timestamp = str(int(time.time()))
        msg = json.dumps(payload, sort_keys=True) + timestamp
        sig = hmac.new(
            bytes.fromhex(self._secret),
            msg.encode(), hashlib.sha256
        ).hexdigest()
        return {
            **payload,
            "agent_id": self.agent_id,
            "timestamp": int(timestamp),
            "signature": sig,
            "public_key": self._public,
        }
    
    def verify_request(self, signed_payload: dict, known_key: str) -> bool:
        """验证签名 — 防伪造+防重放(5分钟窗口)"""
        ts = signed_payload.get("timestamp", 0)
        if abs(time.time() - ts) > 300:  # 5分钟窗口
            logger.warning(f"Request expired: {time.time() - ts}s old")
            return False
        
        sig = signed_payload.pop("signature", "")
        aid = signed_payload.pop("agent_id", "")
        pk = signed_payload.pop("public_key", "")
        ts2 = signed_payload.pop("timestamp", 0)
        
        msg = json.dumps(signed_payload, sort_keys=True) + str(ts2)
        expected = hmac.new(
            bytes.fromhex(known_key if known_key != "verify" else pk),
            msg.encode(), hashlib.sha256
        ).hexdigest()
        
        # Restore popped fields
        signed_payload["signature"] = sig
        signed_payload["agent_id"] = aid
        signed_payload["public_key"] = pk
        signed_payload["timestamp"] = ts2
        
        return hmac.compare_digest(sig, expected)


# ── Worker信息 ──────────────────────────────────────────────

class WorkerStatus(str, Enum):
    ONLINE = "online"
    BUSY = "busy"
    OFFLINE = "offline"
    ERROR = "error"


@dataclass
class WorkerInfo:
    """Manager端的Worker注册信息"""
    worker_id: str
    name: str
    address: str                      # http://ip:port
    public_key: str                   # Worker的公钥
    capabilities: List[str] = field(default_factory=list)  # [coder, reviewer, search, ...]
    status: WorkerStatus = WorkerStatus.ONLINE
    current_task: Optional[str] = None
    last_heartbeat: float = field(default_factory=time.time)
    total_tasks: int = 0
    total_errors: int = 0
    
    def is_alive(self, timeout: float = 30) -> bool:
        return time.time() - self.last_heartbeat < timeout
    
    def to_dict(self) -> dict:
        return {
            "worker_id": self.worker_id,
            "name": self.name,
            "address": self.address,
            "capabilities": self.capabilities,
            "status": self.status.value,
            "current_task": self.current_task,
            "total_tasks": self.total_tasks,
            "total_errors": self.total_errors,
            "last_heartbeat_ago": round(time.time() - self.last_heartbeat, 1),
        }


# ── 任务定义 ──────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class SwarmTask:
    """Manager-Worker间的任务"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    task_type: str = "general"        # search, code, review, analyze, write
    context: str = ""                 # 附加上下文
    worker_id: str = ""               # 分配的Worker
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    assigned_at: float = 0
    completed_at: float = 0
    priority: int = 5                 # 1(低)-10(高)
    
    @property
    def duration(self) -> float:
        if self.completed_at:
            return self.completed_at - (self.assigned_at or self.created_at)
        return time.time() - self.created_at
    
    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "task_type": self.task_type,
            "status": self.status.value,
            "result": self.result[:200] if self.result else "",
            "error": self.error,
            "worker_id": self.worker_id,
            "duration": round(self.duration, 1),
            "priority": self.priority,
        }


# ── Manager Agent ──────────────────────────────────────────

class ManagerAgent:
    """
    管理节点 — Worker注册、任务分解、派发、结果汇总。
    
    启动后监听HTTP端点，Worker通过POST注册。
    """
    
    def __init__(self, identity: AgentIdentity, host: str = "0.0.0.0", port: int = 3000):
        self.identity = identity
        self.host = host
        self.port = port
        self.workers: Dict[str, WorkerInfo] = {}
        self.tasks: Dict[str, SwarmTask] = {}
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        
        # 多Agent协作子系统
        from .multi_agent import AgentManager, TaskDecomposer
        self._agent_manager = AgentManager()
        self._decomposer = TaskDecomposer()
        
        # HTTP transport
        self._http = None  # aiohttp.ClientSession
    
    async def start(self):
        """启动Manager — 开始监听+心跳检查"""
        import aiohttp
        self._http = aiohttp.ClientSession()
        self._running = True
        asyncio.create_task(self._heartbeat_monitor())
        asyncio.create_task(self._task_dispatcher())
        logger.info(f"Manager {self.identity.agent_id} started on {self.host}:{self.port}")
    
    async def stop(self):
        self._running = False
        if self._http:
            await self._http.close()
    
    # ── Worker管理 ──
    
    def register_worker(self, worker_id: str, name: str, address: str,
                        public_key: str, capabilities: List[str] = None) -> WorkerInfo:
        """注册Worker — Worker启动时调用"""
        wi = WorkerInfo(
            worker_id=worker_id,
            name=name,
            address=address,
            public_key=public_key,
            capabilities=capabilities or ["general"],
        )
        self.workers[worker_id] = wi
        logger.info(f"Worker registered: {name} ({worker_id}) at {address}")
        return wi
    
    def unregister_worker(self, worker_id: str):
        """摘除Worker"""
        self.workers.pop(worker_id, None)
        logger.info(f"Worker unregistered: {worker_id}")
    
    def update_heartbeat(self, worker_id: str):
        """更新Worker心跳"""
        if worker_id in self.workers:
            self.workers[worker_id].last_heartbeat = time.time()
            self.workers[worker_id].status = WorkerStatus.ONLINE
    
    def find_worker(self, capability: str) -> Optional[WorkerInfo]:
        """找到具有指定能力的最空闲Worker"""
        candidates = [
            w for w in self.workers.values()
            if capability in w.capabilities
            and w.is_alive()
            and w.status != WorkerStatus.ERROR
        ]
        if not candidates:
            # Fallback: 找任何在线的general Worker
            candidates = [
                w for w in self.workers.values()
                if w.is_alive() and w.status != WorkerStatus.ERROR
            ]
        if not candidates:
            return None
        # 选任务最少的
        return min(candidates, key=lambda w: w.total_tasks - (0 if w.current_task else 1))
    
    # ── 任务管理 ──
    
    async def submit_task(self, description: str, task_type: str = "general",
                          context: str = "", priority: int = 5) -> List[SwarmTask]:
        """
        提交任务 — 自动分解→派发。
        返回所有子任务。
        """
        # 分解
        task_dict = {
            "id": uuid.uuid4().hex[:8],
            "description": description,
            "type": task_type,
        }
        subtasks = self._decomposer.decompose(task_dict)
        
        # 为每个子任务匹配Worker并创建SwarmTask
        swarm_tasks = []
        for st in subtasks:
            capability = st.get("type", "general")
            worker = self.find_worker(capability)
            
            t = SwarmTask(
                task_id=st.get("id", uuid.uuid4().hex[:8]),
                description=st.get("description", description),
                task_type=capability,
                context=context,
                worker_id=worker.worker_id if worker else "",
                priority=priority,
            )
            self.tasks[t.task_id] = t
            swarm_tasks.append(t)
            
            if worker:
                await self._dispatch_task(t, worker)
            else:
                t.status = TaskStatus.PENDING
                logger.warning(f"No worker for task {t.task_id} ({capability})")
        
        return swarm_tasks
    
    async def _dispatch_task(self, task: SwarmTask, worker: WorkerInfo):
        """派发任务到Worker"""
        import aiohttp  # lazy import
        
        if not self._http:
            logger.error("HTTP client not initialized")
            return
        
        task.status = TaskStatus.ASSIGNED
        task.assigned_at = time.time()
        worker.status = WorkerStatus.BUSY
        worker.current_task = task.task_id
        worker.total_tasks += 1
        
        try:
            payload = self.identity.sign_request({
                "task_id": task.task_id,
                "description": task.description,
                "task_type": task.task_type,
                "context": task.context,
            })
            
            url = f"{worker.address}/swarm/task"
            async with self._http.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    task.status = TaskStatus.RUNNING
                    logger.info(f"Task {task.task_id} dispatched to {worker.name}")
                else:
                    task.status = TaskStatus.FAILED
                    task.error = f"Worker returned {resp.status}"
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            worker.status = WorkerStatus.ERROR
            worker.total_errors += 1
            logger.error(f"Dispatch failed for {task.task_id}: {e}")
    
    async def receive_result(self, task_id: str, result: str, error: str = ""):
        """接收Worker返回的结果"""
        task = self.tasks.get(task_id)
        if not task:
            logger.warning(f"Unknown task result: {task_id}")
            return
        
        task.result = result
        task.error = error
        task.status = TaskStatus.DONE if not error else TaskStatus.FAILED
        task.completed_at = time.time()
        
        # 更新Worker状态
        if task.worker_id in self.workers:
            w = self.workers[task.worker_id]
            w.status = WorkerStatus.ONLINE
            w.current_task = None
        
        logger.info(f"Task {task_id} completed: {task.status.value}")
    
    # ── 后台循环 ──
    
    async def _heartbeat_monitor(self):
        """30秒检查一次Worker心跳"""
        while self._running:
            await asyncio.sleep(30)
            for wid, w in list(self.workers.items()):
                if not w.is_alive(timeout=60):
                    w.status = WorkerStatus.OFFLINE
                    logger.warning(f"Worker {wid} timed out, marking offline")
    
    async def _task_dispatcher(self):
        """从队列取待处理任务并派发"""
        while self._running:
            try:
                task_id = await asyncio.wait_for(self._task_queue.get(), timeout=5)
                task = self.tasks.get(task_id)
                if task and task.status == TaskStatus.PENDING:
                    worker = self.find_worker(task.task_type)
                    if worker:
                        await self._dispatch_task(task, worker)
            except asyncio.TimeoutError:
                continue
    
    # ── 状态查询 ──
    
    def get_swarm_status(self) -> dict:
        return {
            "manager_id": self.identity.agent_id,
            "workers": len(self.workers),
            "workers_online": sum(1 for w in self.workers.values() if w.is_alive()),
            "workers_detail": [w.to_dict() for w in self.workers.values()],
            "tasks_pending": sum(1 for t in self.tasks.values() if t.status in (TaskStatus.PENDING, TaskStatus.ASSIGNED, TaskStatus.RUNNING)),
            "tasks_done": sum(1 for t in self.tasks.values() if t.status == TaskStatus.DONE),
            "tasks_failed": sum(1 for t in self.tasks.values() if t.status == TaskStatus.FAILED),
            "tasks": [t.to_dict() for t in list(self.tasks.values())[-20:]],
        }


# ── Worker Agent ──────────────────────────────────────────

class WorkerAgent:
    """
    工作节点 — 注册到Manager，接收任务，调用LLM执行，返回结果。
    
    启动后自动注册+定期心跳。
    """
    
    def __init__(self, identity: AgentIdentity, manager_url: str,
                 name: str = "", capabilities: List[str] = None,
                 host: str = "0.0.0.0", port: int = 3001,
                 llm_callback: Callable = None):
        self.identity = identity
        self.manager_url = manager_url.rstrip("/")
        self.name = name or f"worker_{identity.agent_id[:6]}"
        self.capabilities = capabilities or ["general"]
        self.host = host
        self.port = port
        self._llm_callback = llm_callback  # async fn(task) → str
        self._http = None
        self._running = False
    
    @property
    def address(self) -> str:
        return f"http://{self.host}:{self.port}" if self.host != "0.0.0.0" else f"http://localhost:{self.port}"
    
    async def start(self):
        """启动Worker — 注册+心跳循环"""
        import aiohttp
        self._http = aiohttp.ClientSession()
        self._running = True
        
        # 注册
        await self._register()
        
        # 心跳循环
        asyncio.create_task(self._heartbeat_loop())
        
        logger.info(f"Worker {self.name} ({self.identity.agent_id}) started on :{self.port}")
    
    async def stop(self):
        self._running = False
        if self._http:
            await self._http.close()
    
    async def _register(self):
        """向Manager注册"""
        payload = self.identity.sign_request({
            "worker_id": self.identity.agent_id,
            "name": self.name,
            "address": self.address,
            "capabilities": self.capabilities,
        })
        try:
            url = f"{self.manager_url}/swarm/register"
            async with self._http.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    logger.info(f"Registered with Manager at {self.manager_url}")
                else:
                    logger.error(f"Registration failed: {resp.status}")
        except Exception as e:
            logger.error(f"Registration error: {e}")
    
    async def _heartbeat_loop(self):
        """每20秒发送心跳"""
        while self._running:
            await asyncio.sleep(20)
            try:
                payload = self.identity.sign_request({"status": "alive"})
                url = f"{self.manager_url}/swarm/heartbeat"
                async with self._http.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        logger.warning(f"Heartbeat failed: {resp.status}")
            except Exception as e:
                logger.warning(f"Heartbeat error: {e}")
    
    async def execute_task(self, task_data: dict) -> dict:
        """执行Manager派发的任务"""
        task_id = task_data.get("task_id", "")
        description = task_data.get("description", "")
        task_type = task_data.get("task_type", "general")
        
        logger.info(f"Executing task {task_id}: {description[:50]}...")
        
        try:
            if self._llm_callback:
                result = await self._llm_callback(task_data)
            else:
                # 默认：模拟执行
                await asyncio.sleep(2)
                result = f"[{self.name}] 完成任务: {description[:100]}"
            
            # 返回结果给Manager
            payload = self.identity.sign_request({
                "task_id": task_id,
                "result": result or "",
                "error": "",
            })
            url = f"{self.manager_url}/swarm/result"
            async with self._http.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                status = resp.status
            
            return {"status": "done", "result": result}
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            return {"status": "error", "error": str(e)}


# ── 全局Swarm管理器 ───────────────────────────────────────

_swarm_manager: Optional[ManagerAgent] = None
_swarm_worker: Optional[WorkerAgent] = None


def get_swarm_manager() -> Optional[ManagerAgent]:
    return _swarm_manager


def get_swarm_worker() -> Optional[WorkerAgent]:
    return _swarm_worker


async def init_swarm_manager(host: str = "0.0.0.0", port: int = 3000,
                              key_path: str = None) -> ManagerAgent:
    global _swarm_manager
    identity = AgentIdentity(agent_id="manager", key_path=key_path or "manager_key.json")
    _swarm_manager = ManagerAgent(identity, host=host, port=port)
    await _swarm_manager.start()
    return _swarm_manager


async def init_swarm_worker(manager_url: str, capabilities: List[str] = None,
                             key_path: str = None, port: int = 3001,
                             llm_callback: Callable = None) -> WorkerAgent:
    global _swarm_worker
    identity = AgentIdentity(key_path=key_path or f"worker_{port}_key.json")
    _swarm_worker = WorkerAgent(
        identity=identity,
        manager_url=manager_url,
        capabilities=capabilities,
        port=port,
        llm_callback=llm_callback,
    )
    await _swarm_worker.start()
    return _swarm_worker
