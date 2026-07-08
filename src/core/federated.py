"""meshctx federated — 联邦学习适配器"""
from typing import Any, Dict, List, Optional, Tuple


class FederatedAdapter:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, **kw):
        self._updates: Dict[str, dict] = {}

    def submit_update(self, node_id: str, weights: List[float],
                      samples: int = 1, loss: float = 0.0):
        self._updates[node_id] = {
            "weights": weights,
            "samples": samples,
            "loss": loss,
        }

    def aggregate(self, **kw) -> Optional[List[float]]:
        if not self._updates:
            return None

        total_samples = sum(u["samples"] for u in self._updates.values())
        if total_samples == 0:
            return None

        weight_len = len(next(iter(self._updates.values()))["weights"])
        aggregated = [0.0] * weight_len

        for update in self._updates.values():
            weight_factor = update["samples"] / total_samples
            for i, w in enumerate(update["weights"]):
                aggregated[i] += w * weight_factor

        return aggregated


_singleton: Optional[FederatedAdapter] = None


def get_federated() -> FederatedAdapter:
    global _singleton
    if _singleton is None:
        _singleton = FederatedAdapter()
    return _singleton

from ._stub import _P
