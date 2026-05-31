"""v3.56 Distributed Agent Mesh — tests"""
import pytest
from src.core.distributed_mesh import DistributedAgentMesh, MeshNode, MeshTask, NodeState, get_distributed_mesh

class TestMesh:
    def test_init(self):
        m = DistributedAgentMesh()
        assert m._self.state == NodeState.ONLINE

    def test_assign_task(self):
        m = DistributedAgentMesh()
        node = MeshNode(id="n1", state=NodeState.IDLE)
        m._nodes["n1"] = node
        task = MeshTask(name="test")
        assert m.assign_task(task)
        assert task.assigned_to == "n1"
        assert node.load == 1

    def test_assign_no_capable_nodes(self):
        m = DistributedAgentMesh()
        task = MeshTask(name="test")
        assert not m.assign_task(task)

    def test_complete_task(self):
        m = DistributedAgentMesh()
        node = MeshNode(id="n1", state=NodeState.ONLINE, load=1)
        m._nodes["n1"] = node
        task = MeshTask(name="test", assigned_to="n1")
        m._tasks[task.id] = task
        assert m.complete_task(task.id, result="ok")
        assert task.status == "done"
        assert node.load == 0

    def test_heartbeat(self):
        m = DistributedAgentMesh()
        node = MeshNode(id="n1")
        m._nodes["n1"] = node
        assert m.heartbeat("n1")

    def test_cleanup_offline(self):
        m = DistributedAgentMesh()
        node = MeshNode(id="n1", last_heartbeat=0)
        m._nodes["n1"] = node
        m._node_timeout = 1
        offline = m.cleanup_offline()
        assert "n1" in offline
        assert m._nodes["n1"].state == NodeState.OFFLINE

    def test_stats(self):
        m = DistributedAgentMesh()
        m._nodes["n1"] = MeshNode(id="n1", state=NodeState.ONLINE)
        stats = m.get_stats()
        assert stats["nodes"] == 1

    def test_singleton(self):
        assert get_distributed_mesh() is get_distributed_mesh()
