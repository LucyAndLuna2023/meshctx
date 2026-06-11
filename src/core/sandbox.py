"""Code Sandbox — 开源版 (stub)"""
class CodeSandboxV2:
    def __init__(self, *a, **kw): pass
    def run(self, code: str, *a, **kw) -> dict:
        return {"output": "", "error": "CodeSandbox requires meshctx-core", "exit_code": -1}
    def stats(self): return {}

_sandbox = CodeSandboxV2()
def get_sandbox(): return _sandbox
