"""Project Indexer — 开源版 (stub)"""
class _Indexer:
    def index(self, *a, **kw): pass
    def search(self, *a, **kw): return []
    def stats(self): return {}

_indexer = _Indexer()
def get_indexer(): return _indexer
