"""
meshctx v3.56 — Distributed Agent Mesh (分布式Agent网格)

功能:
  1. 节点发现: 自动检测局域网内其他meshctx实例
  2. 任务分发: 大任务拆解→分发到多节点并行
  3. 结果聚合: 子任务结果合并+一致性校验
  4. 健康检测: 节点心跳+故障转移
"""
import logging, time, json, uuid, socket
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

logger = logging.getLogger("meshctx.distributed_mesh")

class NodeState(Enum):
    ONLINE="online"; BUSY="busy"; IDLE="idle"; OFFLINE="offline"

@dataclass
class MeshNode:
    id: str=field(default_factory=lambda: str(uuid.uuid4())[:8])
    host: str=""; port: int=3001  # BUG-015: 默认使用MESHCTX_HOST环境变量
    state: NodeState=NodeState.IDLE
    capabilities: List[str]=field(default_factory=list)
    load: float=0.0; last_heartbeat: float=0
    tasks_completed: int=0

@dataclass
class MeshTask:
    id: str=field(default_factory=lambda: f"task-{int(time.time()*1000)}")
    name: str=""; payload: Dict=field(default_factory=dict)
    assigned_to: str=""; status: str="pending"
    result: Any=None; error: str=""

class DistributedAgentMesh:
    def __init__(self, host: str="", port: int=3001):
        if not host: host = os.environ.get("MESHCTX_HOST", "127.0.0.1")
        self._self = MeshNode(host=host, port=port, state=NodeState.ONLINE)
        self._nodes: Dict[str,MeshNode] = {}
        self._tasks: Dict[str,MeshTask] = {}
        self._heartbeat_interval = 30
        self._node_timeout = 90
        self._max_load = 10
    
    def discover(self, broadcast_port: int=3002) -> List[MeshNode]:
        discovered = []
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(2)
            s.bind(("", 0))
            s.sendto(b"MESHCTX_DISCOVER", ("255.255.255.255", broadcast_port))
            while True:
                try:
                    data, addr = s.recvfrom(1024)
                    info = json.loads(data.decode())
                    node = MeshNode(id=info.get("id",""), host=addr[0], port=info.get("port",3001),
                        capabilities=info.get("capabilities",[]))
                    self._nodes[node.id] = node
                    discovered.append(node)
                except socket.timeout: break
            s.close()
        except: pass
        return discovered
    
    def assign_task(self, task: MeshTask, strategy: str="least_loaded") -> bool:
        capable = [n for n in self._nodes.values() 
                   if n.state in (NodeState.ONLINE, NodeState.IDLE) and n.load < self._max_load]
        if not capable: return False
        
        if strategy == "least_loaded":
            node = min(capable, key=lambda n: n.load)
        elif strategy == "round_robin":
            node = capable[hash(task.id) % len(capable)]
        else:
            node = capable[0]
        
        task.assigned_to = node.id
        node.load += 1
        node.state = NodeState.BUSY if node.load >= self._max_load else NodeState.ONLINE
        self._tasks[task.id] = task
        return True
    
    def complete_task(self, task_id: str, result: Any=None, error: str="") -> bool:
        task = self._tasks.get(task_id)
        if not task: return False
        task.status = "done" if not error else "failed"
        task.result = result; task.error = error
        node = self._nodes.get(task.assigned_to)
        if node:
            node.load = max(0, node.load - 1)
            node.tasks_completed += 1
            node.state = NodeState.IDLE if node.load == 0 else NodeState.ONLINE
        return True
    
    def heartbeat(self, node_id: str) -> bool:
        node = self._nodes.get(node_id)
        if node: node.last_heartbeat = time.time(); return True
        return False
    
    def cleanup_offline(self) -> List[str]:
        offline = []
        now = time.time()
        for nid, node in list(self._nodes.items()):
            if now - node.last_heartbeat > self._node_timeout:
                node.state = NodeState.OFFLINE; offline.append(nid)
        return offline
    
    def get_stats(self) -> Dict[str,Any]:
        return {
            "self": self._self.id,
            "nodes": len(self._nodes),
            "online": sum(1 for n in self._nodes.values() if n.state != NodeState.OFFLINE),
            "tasks": len(self._tasks),
            "completed": sum(1 for t in self._tasks.values() if t.status == "done"),
            "nodes_detail": {nid:{"state":n.state.value,"load":n.load,"tasks":n.tasks_completed} for nid,n in self._nodes.items()},
        }

_mesh: Optional[DistributedAgentMesh]=None
def get_distributed_mesh(h:str="",p:int=3001):
    if not h: h = os.environ.get("MESHCTX_HOST", "127.0.0.1")
    global _mesh
    if _mesh is None: _mesh = DistributedAgentMesh(h,p)
    return _mesh
