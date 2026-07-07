"""meshctx distributed_mesh — distributed cluster operations"""

import json
import time
import threading
import random
import hashlib
import socket
from dataclasses import dataclass, field
from enum import Enum
import uuid as _uuid
from typing import Dict, List, Optional, Any, Tuple


# ---------------------------------------------------------------------------
# MeshNode dataclass
# ---------------------------------------------------------------------------

@dataclass
class MeshNode:
    """Represents a single node in the distributed mesh cluster.

    Attributes:
        node_id: Unique identifier for this node (e.g. hostname or UUID).
        address: Network address as "host:port" string.
        status:  One of 'active', 'dead', 'unreachable', 'draining'.
        load:    Current load metric (task count or custom weight).
        peers:   List of peer node_ids this node knows about.
        last_heartbeat: Unix timestamp of the most recent heartbeat.
        metadata:       Arbitrary JSON-serialisable extra data.
        labels:         Key-value tags for affinity/selection.
    """
    node_id: str
    address: str
    status: str = "active"
    load: float = 0.0
    peers: List[str] = field(default_factory=list)
    last_heartbeat: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    labels: Dict[str, str] = field(default_factory=dict)

    _MeshNode__init_orig = None  # saved for monkey-patch

    def __init__(self, *args, **kwargs):
        _id = kwargs.pop('id', None)
        _state = kwargs.pop('state', None)
        if _id is not None:
            kwargs['node_id'] = _id
        object.__setattr__(self, 'node_id', kwargs.get('node_id', ''))
        object.__setattr__(self, 'address', kwargs.get('address', ''))
        object.__setattr__(self, 'status', kwargs.get('status', 'active'))
        object.__setattr__(self, 'load', kwargs.get('load', 0.0))
        object.__setattr__(self, 'peers', kwargs.get('peers', []))
        object.__setattr__(self, 'last_heartbeat', kwargs.get('last_heartbeat', time.time()))
        object.__setattr__(self, 'metadata', kwargs.get('metadata', {}))
        object.__setattr__(self, 'labels', kwargs.get('labels', {}))
        object.__setattr__(self, '_state', _state)

    @property
    def state(self):
        return object.__getattribute__(self, '_state')

    @state.setter
    def state(self, val):
        object.__setattr__(self, '_state', val)

    @property
    def id(self):
        return self.node_id

    def to_dict(self) -> Dict[str, Any]:
        """Serialize node to a plain dictionary (JSON-safe)."""
        return {
            "node_id": self.node_id,
            "address": self.address,
            "status": self.status,
            "load": self.load,
            "peers": list(self.peers),
            "last_heartbeat": self.last_heartbeat,
            "metadata": self.metadata,
            "labels": self.labels,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MeshNode":
        """Rehydrate a MeshNode from a dictionary."""
        return cls(
            node_id=d["node_id"],
            address=d["address"],
            status=d.get("status", "active"),
            load=d.get("load", 0.0),
            peers=d.get("peers", []),
            last_heartbeat=d.get("last_heartbeat", time.time()),
            metadata=d.get("metadata", {}),
            labels=d.get("labels", {}),
        )

    def age_seconds(self) -> float:
        """Seconds elapsed since the last heartbeat."""
        return time.time() - self.last_heartbeat

    def is_alive(self, timeout: float = 30.0) -> bool:
        """Return True if the node has sent a heartbeat within *timeout* seconds."""
        return self.status == "active" and self.age_seconds() <= timeout


# ---------------------------------------------------------------------------
# NodeState enum
# ---------------------------------------------------------------------------

class NodeState(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    IDLE = "idle"
    BUSY = "busy"
    DEAD = "dead"


# ---------------------------------------------------------------------------
# MeshTask dataclass
# ---------------------------------------------------------------------------

@dataclass
class MeshTask:
    name: str
    task_id: str = ""
    status: str = "pending"
    assigned_to: Optional[str] = None
    result: Any = None

    def __post_init__(self):
        if not self.task_id:
            self.task_id = str(_uuid.uuid4())[:8]

    @property
    def id(self) -> str:
        return self.task_id


# ---------------------------------------------------------------------------
# DistributedAgentMesh
# ---------------------------------------------------------------------------

class DistributedAgentMesh:
    """Test-compatible distributed agent mesh."""

    def __init__(self):
        self._self = MeshNode(node_id="self", address="127.0.0.1:9000", state=NodeState.ONLINE)
        self._nodes: Dict[str, MeshNode] = {}
        self._tasks: Dict[str, MeshTask] = {}
        self._node_timeout: float = 30.0

    def assign_task(self, task: MeshTask) -> bool:
        for node in self._nodes.values():
            ns = node.state
            if ns in (NodeState.IDLE, NodeState.ONLINE):
                task.assigned_to = node.node_id
                task.status = "assigned"
                self._tasks[task.id] = task
                node.load = node.load + 1
                return True
        return False

    def complete_task(self, task_id: str, result: Any = None) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.status = "done"
        task.result = result
        if task.assigned_to and task.assigned_to in self._nodes:
            node = self._nodes[task.assigned_to]
            node.load = max(0, node.load - 1)
        return True

    def heartbeat(self, node_id: str) -> bool:
        node = self._nodes.get(node_id)
        if node is None:
            return False
        node.last_heartbeat = time.time()
        return True

    def cleanup_offline(self) -> List[str]:
        offline: List[str] = []
        now = time.time()
        for nid, node in list(self._nodes.items()):
            if now - node.last_heartbeat > self._node_timeout:
                offline.append(nid)
                node.state = NodeState.OFFLINE
        return offline

    def get_stats(self) -> Dict[str, Any]:
        return {
            "nodes": len(self._nodes),
            "tasks": len(self._tasks),
            "online": sum(1 for n in self._nodes.values() if n.state == NodeState.ONLINE),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_distributed_mesh_instance: Optional[DistributedAgentMesh] = None


def get_distributed_mesh() -> DistributedAgentMesh:
    global _distributed_mesh_instance
    if _distributed_mesh_instance is None:
        _distributed_mesh_instance = DistributedAgentMesh()
    return _distributed_mesh_instance
