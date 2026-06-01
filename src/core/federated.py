"""
meshctx v3.79 — Federated Learning Adapter (联邦学习适配器)

多节点协作学习: 各自训练→共享梯度→聚合模型, 数据不出本地
"""
import logging, time, numpy as np
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("meshctx.federated")

@dataclass
class ModelUpdate:
    node_id: str; weights: List[float]; samples: int=0
    loss: float=0.0; timestamp: float=field(default_factory=time.time)

class FederatedAdapter:
    def __init__(self, aggregation: str="fedavg"):
        self._updates: Dict[str,List[ModelUpdate]]={}
        self._global_weights: Optional[List[float]]=None
        self._aggregation=aggregation
    
    def submit_update(self, node_id: str, weights: List[float], samples: int=1, loss: float=0.0):
        update = ModelUpdate(node_id=node_id, weights=weights, samples=samples, loss=loss)
        if node_id not in self._updates: self._updates[node_id]=[]
        self._updates[node_id].append(update)
    
    def aggregate(self) -> Optional[List[float]]:
        """FedAvg聚合"""
        total_samples=0; weighted_sum=None
        for node_id, updates in self._updates.items():
            if not updates: continue
            latest = updates[-1]
            if weighted_sum is None: weighted_sum = [0.0]*len(latest.weights)
            for i,w in enumerate(latest.weights):
                weighted_sum[i] += w * latest.samples
            total_samples += latest.samples
        
        if total_samples>0 and weighted_sum:
            self._global_weights = [w/total_samples for w in weighted_sum]
        return self._global_weights
    
    def get_stats(self) -> Dict:
        return {"nodes": len(self._updates), "global_weights": self._global_weights is not None}

_fed = None
def get_federated():
    global _fed
    if _fed is None: _fed = FederatedAdapter()
    return _fed
