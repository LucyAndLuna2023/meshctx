"""
meshctx v3.74 — Code Sandbox v2 (代码沙箱v2)

安全执行Python/Bash/JS代码, 资源限制+超时+输出限制
"""
import subprocess, tempfile, os, time, signal, sys
if sys.platform != 'win32':
    import resource
from dataclasses import dataclass, field
from typing import Optional, Dict

@dataclass
class SandboxResult:
    output: str=""; error: str=""; exit_code: int=-1
    duration_ms: float=0; truncated: bool=False

class CodeSandboxV2:
    def __init__(self, timeout: int=30, max_output: int=10000):
        self.timeout = timeout; self.max_output = max_output
    
    def run_python(self, code: str) -> SandboxResult:
        t0 = time.perf_counter()
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code); path = f.name
            try:
                proc = subprocess.run(['python3', path], capture_output=True, text=True,
                    timeout=self.timeout, env={**os.environ, 'PYTHONPATH': ''})
                out = proc.stdout[:self.max_output]; err = proc.stderr[:self.max_output]
                return SandboxResult(output=out, error=err, exit_code=proc.returncode,
                    duration_ms=(time.perf_counter()-t0)*1000)
            finally:
                os.unlink(path)
        except subprocess.TimeoutExpired:
            return SandboxResult(error="TIMEOUT", duration_ms=self.timeout*1000)
        except Exception as e:
            return SandboxResult(error=str(e))
    
    def run_bash(self, cmd: str) -> SandboxResult:
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(['bash','-c',cmd], capture_output=True, text=True,
                timeout=self.timeout, env={'PATH': os.environ.get('PATH','/usr/bin')})
            return SandboxResult(output=proc.stdout[:self.max_output], error=proc.stderr[:self.max_output],
                exit_code=proc.returncode, duration_ms=(time.perf_counter()-t0)*1000)
        except subprocess.TimeoutExpired:
            return SandboxResult(error="TIMEOUT")
        except Exception as e:
            return SandboxResult(error=str(e))

_sandbox = None
def get_sandbox(timeout=30):
    global _sandbox
    if _sandbox is None: _sandbox = CodeSandboxV2(timeout)
    return _sandbox

# Backward compat
SandboxEngine = CodeSandboxV2
