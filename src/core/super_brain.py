"""meshctx super_brain — 转发到 UnifiedBrain (brain_wired.py)"""
# 原 super_brain.py 包含 6 个重复的简化版脑区实现。
# 现已全部替换为 brain_wired.py 中的真实模块。
# 保持文件名兼容，所有调用转发。

from .brain_wired import UnifiedBrain, SuperBrain, BrainState, NEURAL_PATHWAYS

__all__ = ["UnifiedBrain", "SuperBrain", "BrainState", "NEURAL_PATHWAYS"]
