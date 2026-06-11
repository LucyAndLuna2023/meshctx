"""Profile Manager — 开源版 (stub)"""
class ProfileManager:
    def __init__(self, *a, **kw): pass
    def list_profiles(self) -> list: return ["default"]
    def get_profile(self, name: str = "default") -> dict:
        return {"name": name, "config": {}}
    def create_profile(self, *a, **kw): return True
    def stats(self): return {}
