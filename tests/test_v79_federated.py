"""v3.79 Federated — tests"""
import pytest
from src.core.federated import FederatedAdapter, get_federated

class TestFederated:
    def test_submit_aggregate(self):
        f = FederatedAdapter()
        f.submit_update("n1", [1.0,2.0,3.0], samples=10, loss=0.1)
        f.submit_update("n2", [2.0,3.0,4.0], samples=5, loss=0.2)
        w = f.aggregate()
        assert w is not None; assert len(w) == 3
        # FedAvg: (1*10+2*5)/15=1.33, (2*10+3*5)/15=2.33, (3*10+4*5)/15=3.33
        assert abs(w[0]-1.33)<0.1

    def test_singleton(self):
        assert get_federated() is get_federated()
