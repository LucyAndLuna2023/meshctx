"""
meshctx v3.62 — Context Compression Engine (上下文压缩引擎)

问题: LLM上下文窗口有限(128K), 多轮对话容易溢出
方案: 智能压缩→保留关键信息→丢弃冗余→分层存储

功能:
  1. 摘要压缩: 长对话→要点摘要(L0原始→L1摘要→L2元摘要)
  2. 关键帧提取: 保留转折点/决策点
  3. 压缩率可配置: 50%-95%
"""
import logging, time, re, hashlib
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("meshctx.context_compressor")

@dataclass
class CompressedBlock:
    original_len: int; compressed_len: int; ratio: float
    summary: str; key_points: List[str]; timestamp: float=field(default_factory=time.time)

class ContextCompressor:
    def __init__(self, max_tokens: int=8000, compression_ratio: float=0.5):
        self._max_tokens = max_tokens; self._ratio = compression_ratio
        self._history: deque=deque(maxlen=50)
    
    def compress(self, text: str, preserve_keywords: List[str]=None) -> CompressedBlock:
        """压缩文本"""
        orig = len(text)
        if orig < 500:  # 太短不压缩
            return CompressedBlock(original_len=orig, compressed_len=orig, ratio=1.0, summary=text, key_points=[])
        
        # 提取关键句(包含关键词/数字/引号的句子)
        sentences = re.split(r'(?<=[.!?。！？])\s+', text)
        keywords = set(preserve_keywords or [])
        
        scored = []
        for s in sentences:
            score = 0
            for kw in keywords:
                if kw.lower() in s.lower(): score += 3
            if re.search(r'\d+', s): score += 1  # 包含数字
            if len(s) < 20: score -= 1  # 太短可能无意义
            if any(c in s for c in '"\'「」'): score += 1  # 引号=引用
            scored.append((score, s))
        
        # 按得分排序+压缩比截断
        scored.sort(key=lambda x:-x[0])
        target_len = int(orig * self._ratio)
        compressed = []; current_len = 0; key_points = []
        
        for score, s in scored:
            if current_len + len(s) > target_len: break
            compressed.append(s); current_len += len(s)
            if score >= 2: key_points.append(s[:80])
        
        summary = " ".join(compressed)
        block = CompressedBlock(original_len=orig, compressed_len=len(summary),
                                ratio=round(len(summary)/orig, 2), summary=summary,
                                key_points=key_points[:10])
        self._history.append(block)
        return block
    
    def hierarchical_compress(self, text: str, levels: int=2) -> List[CompressedBlock]:
        """分层压缩 L0→L1→L2"""
        results = [self.compress(text)]
        for _ in range(levels-1):
            prev = results[-1].summary
            if len(prev) < 200: break
            results.append(self.compress(prev))
        return results
    
    def get_stats(self) -> Dict:
        if not self._history: return {"compressions": 0}
        ratios = [b.ratio for b in self._history]
        return {"compressions": len(self._history),
                "avg_ratio": round(sum(ratios)/len(ratios),2),
                "total_saved_chars": sum(b.original_len-b.compressed_len for b in self._history)}

_compressor = None
def get_context_compressor(max_tokens=8000, ratio=0.5):
    global _compressor
    if _compressor is None: _compressor = ContextCompressor(max_tokens, ratio)
    return _compressor
