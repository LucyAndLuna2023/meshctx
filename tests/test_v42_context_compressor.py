"""v3.42 Context Compression tests"""
import pytest, numpy as np

class TestCompressedMemory:
    def test_add_and_retrieve(self):
        from src.core.context_compressor import CompressedMemory
        mem = CompressedMemory(dim=64, capacity=10)
        v1 = np.random.randn(64)
        mem.add(v1, {'role': 'user'})
        assert len(mem.slots) == 1
        
        results = mem.retrieve(v1, top_k=3)
        assert len(results) == 1
        assert results[0][1] > 0.9  # 高相似度
    
    def test_deduplicate_similar(self):
        from src.core.context_compressor import CompressedMemory
        mem = CompressedMemory(dim=32, capacity=10)
        v = np.ones(32)
        mem.add(v)
        mem.add(v + 0.001)  # 几乎相同
        assert len(mem.slots) == 1  # 去重
    
    def test_capacity_limit(self):
        from src.core.context_compressor import CompressedMemory
        mem = CompressedMemory(dim=16, capacity=5)
        for i in range(10):
            mem.add(np.random.randn(16))
        assert len(mem.slots) == 5  # FIFO淘汰

class TestContextCompressor:
    def test_add_frame(self):
        from src.core.context_compressor import ContextCompressor
        cc = ContextCompressor(dim=32)
        f = cc.add_frame('user', 'hello world')
        assert f.role == 'user'
        assert len(cc.frames) == 1
    
    def test_compress_light(self):
        from src.core.context_compressor import ContextCompressor, CompressionLevel
        cc = ContextCompressor(dim=32)
        for i in range(20):
            cc.add_frame('user', f'message {i}' * (10 if i % 3 == 0 else 1))
        result = cc.compress(CompressionLevel.LIGHT)
        assert len(result) <= 20
    
    def test_compress_medium(self):
        from src.core.context_compressor import ContextCompressor, CompressionLevel
        cc = ContextCompressor(dim=32)
        for i in range(20):
            cc.add_frame('user', f'message {i}')
        result = cc.compress(CompressionLevel.MEDIUM)
        stats = cc.get_stats()
        assert 'compression_ratio' in stats
        assert stats['total_frames'] == 20
    
    def test_compress_deep(self):
        from src.core.context_compressor import ContextCompressor, CompressionLevel
        cc = ContextCompressor(dim=32)
        for i in range(20):
            cc.add_frame('user', f'message {i}')
        result = cc.compress(CompressionLevel.DEEP)
        # Deep: only recent frames kept
        assert len(result) <= 10
    
    def test_reconstruct(self):
        from src.core.context_compressor import ContextCompressor, CompressionLevel
        cc = ContextCompressor(dim=32)
        cc.add_frame('system', 'you are helpful')
        cc.add_frame('user', 'hello')
        cc.add_frame('assistant', 'hi there')
        cc.compress(CompressionLevel.MEDIUM)
        ctx = cc.reconstruct_context()
        assert 'hello' in ctx or 'hi' in ctx
    
    def test_stats(self):
        from src.core.context_compressor import ContextCompressor, CompressionLevel
        cc = ContextCompressor(dim=32)
        for i in range(10):
            cc.add_frame('user', f'msg {i}')
        cc.compress(CompressionLevel.MEDIUM)
        stats = cc.get_stats()
        assert stats['total_frames'] == 10
        assert 'tokens_saved_est' in stats
