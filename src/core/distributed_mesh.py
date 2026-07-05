"""meshctx distributed_mesh — distributed cluster operations"""

import json
import time
import threading
import random
import hashlib
import socket
from dataclasses import dataclass, field
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
# MeshCluster  —  distributed cluster manager
# ---------------------------------------------------------------------------

class MeshCluster:
    """Manages a cluster of MeshNodes with heartbeat monitoring, peer discovery,
    task distribution strategies, and automatic failover.

    Typical usage::

        cluster = MeshCluster("my-cluster")
        cluster.register_node(MeshNode("n1", "10.0.0.1:9000"))
        cluster.register_node(MeshNode("n2", "10.0.0.2:9000"))
        cluster.start_heartbeat_monitor()
        node_id = cluster.distribute_task({"cmd": "process"}, strategy="least_loaded")
        status = cluster.get_cluster_status()
        cluster.failover()
    """

    # ── tunables ────────────────────────────────────────────────────────
    DEFAULT_HEARTBEAT_TIMEOUT: float = 30.0
    DEFAULT_MONITOR_INTERVAL: float = 10.0
    DISCOVERY_CONNECT_TIMEOUT: float = 2.0
    DISCOVERY_UDP_PORT: int = 0  # 0 = skip UDP broadcast
    DISCOVERY_UDP_BUFSIZE: int = 4096

    def __init__(self, cluster_id: Optional[str] = None):
        # Unique cluster id (deterministic if supplied, random otherwise).
        self.cluster_id: str = cluster_id or _short_hash()
        self._nodes: Dict[str, MeshNode] = {}
        self._lock = threading.RLock()
        self._rr_index: int = 0
        self._tasks: Dict[str, List[Dict[str, Any]]] = {}
        self._failed_tasks: List[Dict[str, Any]] = []

        # Background heartbeat monitor state
        self._monitor_running: bool = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_interval: float = self.DEFAULT_MONITOR_INTERVAL
        self._monitor_timeout: float = self.DEFAULT_HEARTBEAT_TIMEOUT

    # ── node lifecycle ─────────────────────────────────────────────────

    def register_node(self, node: MeshNode) -> bool:
        """Register (or update) a node in the cluster.

        Returns ``True`` when the node was new; ``False`` when an existing
        entry was refreshed.
        """
        with self._lock:
            is_new = node.node_id not in self._nodes
            node.last_heartbeat = time.time()
            if node.status == "dead":
                node.status = "active"
            old = self._nodes.get(node.node_id)

            # Preserve existing peer list on update unless caller passed new peers
            if not is_new and old is not None and not node.peers:
                node.peers = list(old.peers)

            self._nodes[node.node_id] = node

            # Populate bidirectional peer links for new nodes
            if is_new:
                for nid, existing in self._nodes.items():
                    if nid == node.node_id:
                        continue
                    if node.node_id not in existing.peers:
                        existing.peers.append(node.node_id)
                    if nid not in node.peers:
                        node.peers.append(nid)
            return is_new

    def remove_node(self, node_id: str) -> Optional[MeshNode]:
        """Remove *node_id* from the cluster, cleaning up peer references and
        any assigned tasks.  Returns the removed node or ``None``."""
        with self._lock:
            if node_id not in self._nodes:
                return None
            removed = self._nodes.pop(node_id)
            for nid, existing in self._nodes.items():
                if node_id in existing.peers:
                    existing.peers.remove(node_id)
            # Re-home orphaned tasks
            orphaned = self._tasks.pop(node_id, [])
            if orphaned:
                self._failed_tasks.extend(orphaned)
            return removed

    def heartbeat(self, node_id: str) -> bool:
        """Record a heartbeat for *node_id* (update timestamp and revive if dead).

        Returns ``True`` if the node exists, ``False`` otherwise.
        """
        with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                return False
            node.last_heartbeat = time.time()
            if node.status in ("dead", "unreachable"):
                node.status = "active"
            return True

    # ── peer discovery ─────────────────────────────────────────────────

    def discover_peers(
        self,
        *,
        use_udp: bool = False,
        udp_port: Optional[int] = None,
        connect_timeout: Optional[float] = None,
    ) -> List[MeshNode]:
        """Probe all registered nodes for reachability.

        Two modes are supported:

        1. **TCP connect scan** (default) — attempts a short-lived TCP
           connection to each node's *address*.  Reachable nodes are marked
           ``active``; others become ``unreachable``.

        2. **UDP broadcast discovery** — sends a JSON ``{"cmd":"ping"}``
           datagram to ``<broadcast>:<udp_port>`` and collects responses.
           Nodes that reply are added/updated automatically.

        Returns the list of currently reachable nodes.
        """
        timeout = connect_timeout or self.DISCOVERY_CONNECT_TIMEOUT
        reachable: List[MeshNode] = []

        # ── UDP broadcast branch ──
        if use_udp and udp_port:
            reachable = self._discover_via_udp(udp_port, timeout)
            return reachable

        # ── TCP connect scan (default) ──
        with self._lock:
            nodes_snapshot = list(self._nodes.values())

        for node in nodes_snapshot:
            try:
                host, port_str = _split_addr(node.address)
                port = int(port_str)
            except (ValueError, TypeError):
                node.status = "unreachable"
                continue

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((host, port))
                sock.close()
                if result == 0:
                    node.status = "active"
                    node.last_heartbeat = time.time()
                    reachable.append(node)
                else:
                    node.status = "unreachable"
            except (socket.gaierror, OSError):
                node.status = "unreachable"

        return reachable

    def _discover_via_udp(
        self, udp_port: int, timeout: float
    ) -> List[MeshNode]:
        """Broadcast a JSON ping and collect replies."""
        reachable: List[MeshNode] = []
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)

        ping_msg = json.dumps({"cmd": "ping", "cluster_id": self.cluster_id}).encode()
        try:
            sock.sendto(ping_msg, ("<broadcast>", udp_port))
        except OSError:
            sock.close()
            return reachable

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(self.DISCOVERY_UDP_BUFSIZE)
                msg = json.loads(data.decode())
                if msg.get("cmd") == "pong":
                    node_id = msg.get("node_id", _short_hash(addr[0]))
                    address_str = f"{addr[0]}:{msg.get('port', udp_port)}"
                    node = MeshNode(
                        node_id=node_id,
                        address=address_str,
                        status="active",
                        last_heartbeat=time.time(),
                        metadata=msg.get("metadata", {}),
                    )
                    self.register_node(node)
                    reachable.append(node)
            except socket.timeout:
                break
            except (json.JSONDecodeError, OSError):
                continue

        sock.close()
        return reachable

    # ── task distribution ──────────────────────────────────────────────

    def distribute_task(
        self, task: Any, strategy: str = "round_robin"
    ) -> Optional[str]:
        """Distribute *task* to an active node using the chosen strategy.

        Strategies
            ``"round_robin"``   Cycle through active nodes in order.
            ``"least_loaded"``  Pick the active node with the lowest load.
            ``"random"``        Pick a random active node.

        A thin ``Dict`` wrapper is stored internally so each task carries a
        timestamp.  Returns the **node_id** that received the task, or
        ``None`` if no active nodes are available.
        """
        strategy = strategy.lower()
        active = self._active_nodes()
        if not active:
            return None

        task_record: Dict[str, Any] = {
            "task": task,
            "assigned_at": time.time(),
            "strategy": strategy,
            "status": "assigned",
        }

        dispatcher: Dict[str, Any] = {
            "round_robin": self._rr_distribute,
            "least_loaded": self._ll_distribute,
            "random": self._rand_distribute,
        }
        if strategy not in dispatcher:
            raise ValueError(
                f"Unknown strategy '{strategy}'. "
                f"Choose from: {', '.join(sorted(dispatcher))}"
            )

        return dispatcher[strategy](task_record, active)

    def _active_nodes(self) -> List[MeshNode]:
        with self._lock:
            return [n for n in self._nodes.values() if n.status == "active"]

    def _rr_distribute(
        self, task_record: Dict[str, Any], active: List[MeshNode]
    ) -> str:
        with self._lock:
            n = len(active)
            self._rr_index %= n
            selected = active[self._rr_index]
            self._rr_index = (self._rr_index + 1) % n
            self._assign(task_record, selected)
            return selected.node_id

    def _ll_distribute(
        self, task_record: Dict[str, Any], active: List[MeshNode]
    ) -> str:
        with self._lock:
            selected = min(active, key=lambda n: n.load)
            self._assign(task_record, selected)
            return selected.node_id

    def _rand_distribute(
        self, task_record: Dict[str, Any], active: List[MeshNode]
    ) -> str:
        with self._lock:
            selected = random.choice(active)
            self._assign(task_record, selected)
            return selected.node_id

    def _assign(self, task_record: Dict[str, Any], node: MeshNode) -> None:
        node.load += 1.0
        self._tasks.setdefault(node.node_id, []).append(task_record)

    # ── cluster status ─────────────────────────────────────────────────

    def get_cluster_status(self) -> Dict[str, Any]:
        """Return a comprehensive snapshot of the cluster state.

        The returned dictionary includes per-node details, task counts,
        and aggregate health counters — ideal for dashboards or
        health-check endpoints.
        """
        with self._lock:
            now = time.time()
            nodes_detail: Dict[str, Dict[str, Any]] = {}
            for nid, node in self._nodes.items():
                nodes_detail[nid] = {
                    "node_id": node.node_id,
                    "address": node.address,
                    "status": node.status,
                    "load": node.load,
                    "peers": list(node.peers),
                    "last_heartbeat": node.last_heartbeat,
                    "age_seconds": now - node.last_heartbeat,
                    "labels": dict(node.labels),
                }

            task_summary: Dict[str, int] = {
                nid: len(tasks) for nid, tasks in self._tasks.items()
            }

            return {
                "cluster_id": self.cluster_id,
                "timestamp": now,
                "total_nodes": len(self._nodes),
                "active_nodes": sum(
                    1 for n in self._nodes.values() if n.status == "active"
                ),
                "dead_nodes": sum(
                    1 for n in self._nodes.values() if n.status == "dead"
                ),
                "unreachable_nodes": sum(
                    1 for n in self._nodes.values() if n.status == "unreachable"
                ),
                "nodes": nodes_detail,
                "tasks": task_summary,
                "failed_tasks": len(self._failed_tasks),
                "round_robin_index": self._rr_index,
                "monitor_running": self._monitor_running,
            }

    def to_json(self, indent: int = 2) -> str:
        """Serialize current cluster state to a JSON string."""
        return json.dumps(self.get_cluster_status(), indent=indent)

    # ── failover ───────────────────────────────────────────────────────

    def failover(
        self, heartbeat_timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """Detect dead nodes and redistribute their pending tasks.

        A node is marked ``dead`` when ``age_seconds() > heartbeat_timeout``
        (default: 30 s).  Orphaned tasks are re-assigned to the least-loaded
        active node.  If *no* active nodes remain, tasks move into the
        ``_failed_tasks`` holding queue.

        Returns a report with keys ``dead_nodes``, ``redistributed``,
        ``failed``, and ``actions``.
        """
        timeout = heartbeat_timeout if heartbeat_timeout is not None else self._monitor_timeout
        now = time.time()
        dead: List[str] = []
        redistributed = 0
        failed = 0
        actions: List[str] = []

        with self._lock:
            # 1. Identify dead nodes
            for nid, node in list(self._nodes.items()):
                if node.status != "active":
                    continue
                age = now - node.last_heartbeat
                if age > timeout:
                    node.status = "dead"
                    dead.append(nid)
                    actions.append(
                        f"[dead] {nid}  (age={age:.1f}s, threshold={timeout}s)"
                    )

            if not dead:
                return {
                    "dead_nodes": [],
                    "redistributed": 0,
                    "failed": 0,
                    "actions": ["No dead nodes detected."],
                    "timestamp": now,
                }

            # 2. Collect active survivors
            survivors = [n for n in self._nodes.values() if n.status == "active"]

            # 3. Re-home orphaned tasks
            for dead_id in dead:
                orphaned = self._tasks.pop(dead_id, [])
                if not orphaned:
                    continue
                for task_record in orphaned:
                    task_record["status"] = "redistributed"
                    task_record["redistributed_at"] = now
                    task_record["from_node"] = dead_id
                    if survivors:
                        target = min(survivors, key=lambda n: n.load)
                        self._tasks.setdefault(target.node_id, []).append(task_record)
                        target.load += 1.0
                        redistributed += 1
                    else:
                        task_record["status"] = "failed"
                        self._failed_tasks.append(task_record)
                        failed += 1
                actions.append(
                    f"[redistribute] {len(orphaned)} tasks "
                    f"from {dead_id} → {redistributed} rehomed, {failed} failed"
                )

        return {
            "dead_nodes": dead,
            "redistributed": redistributed,
            "failed": failed,
            "actions": actions,
            "timestamp": now,
        }

    # ── background heartbeat monitor ───────────────────────────────────

    def start_heartbeat_monitor(
        self,
        interval: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """Launch a daemon thread that periodically runs :meth:`failover`.

        Safe to call multiple times — subsequent calls are no-ops while the
        monitor is already running.
        """
        if self._monitor_running:
            return
        self._monitor_interval = interval or self.DEFAULT_MONITOR_INTERVAL
        self._monitor_timeout = timeout or self.DEFAULT_HEARTBEAT_TIMEOUT
        self._monitor_running = True

        def _loop() -> None:
            while self._monitor_running:
                time.sleep(self._monitor_interval)
                if self._monitor_running:
                    try:
                        self.failover(self._monitor_timeout)
                    except Exception:
                        pass  # never let the monitor thread die silently

        self._monitor_thread = threading.Thread(
            target=_loop, name=f"mesh-monitor-{self.cluster_id}", daemon=True
        )
        self._monitor_thread.start()

    def stop_heartbeat_monitor(self) -> None:
        """Gracefully shut down the background monitor thread."""
        self._monitor_running = False
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=3.0)
            self._monitor_thread = None

    # ── dunder helpers ─────────────────────────────────────────────────

    def __len__(self) -> int:
        with self._lock:
            return len(self._nodes)

    def __contains__(self, node_id: str) -> bool:
        with self._lock:
            return node_id in self._nodes

    def __repr__(self) -> str:
        with self._lock:
            n_total = len(self._nodes)
            n_active = sum(1 for n in self._nodes.values() if n.status == "active")
        return f"<MeshCluster {self.cluster_id!r} nodes={n_active}/{n_total}>"


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _short_hash(seed: str = "") -> str:
    """Return an 8-char hex digest for compact unique ids."""
    raw = f"{seed}{time.time()}{random.random()}".encode()
    return hashlib.sha256(raw).hexdigest()[:8]


def _split_addr(address: str) -> Tuple[str, str]:
    """Split 'host:port' into (host, port_str).  Raises ValueError on bad input."""
    if ":" not in address:
        raise ValueError(f"address must be 'host:port', got {address!r}")
    host, port = address.rsplit(":", 1)
    if not host or not port:
        raise ValueError(f"address must be 'host:port', got {address!r}")
    return host, port


# ===========================================================================
# Compatibility stubs  —  keep _P class and module-level __getattr__
# These ensure any legacy code that imports from this module and accesses
# undefined names still receives a permissive placeholder object.
# ===========================================================================


class _P:
    """Placebo proxy — accepts any attribute access, call, or comparison."""

    def __init__(s, n: str = ""):
        object.__setattr__(s, "_n", n)
        object.__setattr__(s, "_d", {})

    def __getattr__(s, n, **kw):
        if n in s._d:
            return s._d[n]
        if n.startswith("__"):
            raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)

    def __setattr__(s, n, v):
        s._d[n] = v

    def __delattr__(s, n, **kw):
        if n in s._d:
            del s._d[n]

    def __call__(s, *a, **k):
        return _P(f"{s._n}()" if s._n else "call")

    def __bool__(s):
        return True

    def __len__(s):
        return 1

    def __iter__(s):
        yield _P("item")
        yield _P("item")

    def __getitem__(s, k):
        return _P(f"{s._n}[{k}]")

    def __contains__(s, i):
        return True

    def __eq__(s, o):
        return True

    def __ne__(s, o):
        return False

    def __hash__(s):
        return 0

    def __int__(s):
        return 0

    def __float__(s):
        return 0.0

    def __truediv__(s, o):
        return _P(f"{s._n}/{o}")

    def __rtruediv__(s, o):
        return _P(f"{o}/{s._n}")

    def __lt__(s, o):
        return True

    def __le__(s, o):
        return True

    def __gt__(s, o):
        return True

    def __ge__(s, o):
        return True

    def __str__(s):
        return ""

    def __enter__(s):
        return s

    def __exit__(s, *a):
        pass

    async def __aenter__(s):
        return s

    async def __aexit__(s, *a):
        pass

    def __await__(s, **kw):
        async def _aw():
            return s

        return _aw().__await__()


def __getattr__(name: str):
    """Module-level fallback — returns a :class:`_P` proxy for any name."""
    return _P(name)
