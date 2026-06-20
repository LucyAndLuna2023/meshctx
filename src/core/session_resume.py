"""Session Resume — 开源版 (stub)"""
import logging

logger = logging.getLogger("meshctx.session_resume")

class _SessionResume:
    def resume(self, *a, **kw): return None
    def stats(self): return {}
    def detect_previous_session(self):
        """检测是否存在上次会话存档"""
        return None  # 开源版不实现自动恢复
    def restore(self, session_id):
        """恢复指定会话"""
        return {"context_continuity": 0, "items_restored": {"decisions": 0, "rules": 0}, "resume_time_ms": 0}
    def apply_to_kernel(self, kernel):
        """将会话上下文注入内核"""
        return []

_resume = _SessionResume()
def get_session_resume(): return _resume
