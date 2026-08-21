"""
meshctx Sandbox v3.50 — 安全代码执行沙箱
========================================
提供受限的 Python/Bash 代码执行环境，具备 syscall 限制、
资源控制、超时管理、危险模式检测等安全机制。

安全策略:
  1. 导入白名单: 仅允许安全模块 (math, json, re, collections, etc.)
  2. 危险模式拦截: import os/subprocess/sys/socket 等直接拒绝
  3. 资源限制: CPU 时间上限 + 内存上限
  4. 超时控制: 可配置超时, 超时自动 kill 子进程
  5. 文件访问限制: 仅允许读写指定目录
  6. 网络隔离: 禁止所有网络访问

执行模式:
  - python: 在受限的子进程中执行 Python 代码片段
  - bash: 在受限的 subprocess 中执行 shell 命令

使用示例:
  sandbox = get_sandbox()
  result = await sandbox.execute("print(1+1)", mode="python", timeout=5)
  print(result.stdout)  # "2
"

  stats = sandbox.get_sandbox_stats()
  # → {"total_executions": 42, "success_rate": 0.95, ...}
"""
# NOTE: 本文件为 meshctx 开源接口 stub。核心实现位于私有仓库 meshctx-core。
# 商业/完整版: pip install meshctx-core (需授权)。访问接口将抛 NotImplementedError。
from __future__ import annotations
from enum import Enum
from abc import ABC
from dataclasses import dataclass, field
import re

class _MeshCtxStubProxy:
    """未导出符号的优雅降级代理: 导入成功, 调用/属性访问时提示需 meshctx-core。"""
    def __init__(self, name):
        self._name = name
    def __getattr__(self, attr):
        return _MeshCtxStubProxy(f"{self._name}.{attr}")
    def __call__(self, *args, **kwargs):
        raise NotImplementedError(f"meshctx-core required (private repo): {self._name}")
    def __repr__(self):
        return f"<meshctx stub {self._name}>"

def __getattr__(name):
    return _MeshCtxStubProxy(name)

logger = "logger"
class ExecutionStatus(str, Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    TIMEOUT = 'timeout'
    KILLED = 'killed'
    BLOCKED = 'blocked'
    MEMORY_LIMIT = 'memory_limit'

@dataclass
class ExecutionResult:
    """沙箱执行结果"""
    execution_id: str = ''
    status: ExecutionStatus = None
    stdout: str = ''
    stderr: str = ''
    return_code: int = 0
    duration_ms: float = 0.0
    peak_memory_mb: float = 0.0
    timeout_seconds: float = 30.0
    blocked_reason: str = ''
    mode: str = 'python'
    code_truncated: str = ''
    created_at: float = None
    def exit_code(self):
        raise NotImplementedError("meshctx-core required (private repo)")

    def output(self):
        raise NotImplementedError("meshctx-core required (private repo)")

    def error(self):
        raise NotImplementedError("meshctx-core required (private repo)")

    def to_dict(self, **kw) -> Dict:
        raise NotImplementedError("meshctx-core required (private repo)")

    def is_success(self, **kw) -> bool:
        raise NotImplementedError("meshctx-core required (private repo)")

    def output(self, **kw) -> str:
        """stdout + stderr 合并输出"""
        raise NotImplementedError("meshctx-core required (private repo)")


class CodeScanner:
    """代码安全扫描器 — 检测危险模式（开源降级版）

    完整版（更强规则库、语义分析、自定义策略）见 meshctx-core。
    本实现提供基础但可工作的危险模式检测，保障终端/沙箱在开源环境安全可用。
    """

    _BASH_DANGEROUS = (
        (r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s+(/\s*$|/\*)", "rm -rf 根目录"),
        (r":\(\)\s*\{", "fork bomb"),
        (r"\bmkfs\b", "格式化磁盘"),
        (r"\bdd\s+if=", "dd 覆写磁盘"),
        (r">\s*/dev/sd", "覆写块设备"),
        (r"\bshutdown\b", "关机"),
        (r"\breboot\b", "重启"),
        (r"\bhalt\b", "停机"),
        (r"\bpoweroff\b", "断电"),
        (r"\bchmod\s+-R\s+777\s+/", "chmod -R 777 /"),
        (r"\bmv\s+/\s", "移动根目录"),
        (r"\bcurl\b.*\|\s*(ba)?sh", "curl|sh 远程执行"),
        (r"\bwget\b.*\|\s*(ba)?sh", "wget|sh 远程执行"),
        (r"\bpython3?\b.*\|\s*(ba)?sh", "python|sh 管道执行"),
    )

    _PYTHON_DANGEROUS = {
        "os.system": r"os\.system\s*\(",
        "subprocess_shell": r"subprocess\.[a-z_]+\([^)]*shell\s*=\s*True",
        "subprocess": r"\bsubprocess\.",
        "eval": r"\beval\s*\(",
        "exec": r"\bexec\s*\(",
        "open_write": r"\bopen\([^)]*['\"][wa]['\"]",
        "shutil_rmtree": r"shutil\.rmtree\s*\(",
        "socket": r"\bsocket\.(socket|connect|create_connection)\s*\(",
        "__import__": r"__import__\s*\(",
        "ctypes": r"\bctypes\.(CDLL|WinDLL|PyDLL)\s*\(",
        "pickle_loads": r"pickle\.loads\s*\(",
        "yaml_load": r"yaml\.load\s*\([^)]*\)",
        "file_delete": r"os\.(remove|unlink|rmdir)\s*\(",
    }

    @classmethod
    def scan_python(cls, code: str, **kw) -> list:
        """扫描 Python 代码中的危险模式，返回命中的危险模式名列表（空列表=安全）。"""
        if not isinstance(code, str) or not code.strip():
            return []
        return [name for name, pat in cls._PYTHON_DANGEROUS.items() if re.search(pat, code)]

    @classmethod
    def scan_bash(cls, command: str, **kw) -> tuple:
        """扫描 Bash 命令，返回 (是否安全, 原因)。"""
        if not isinstance(command, str) or not command.strip():
            return False, "空命令"
        cmd = command.strip()
        for pat, reason in cls._BASH_DANGEROUS:
            if re.search(pat, cmd):
                return False, reason
        return True, ""


_PYTHON_RUNNER_TEMPLATE = '\nimport sys\nimport json\nimport time\nimport traceback\ntry:\n    import resource  # Unix-only; Windows 上不存在\nexcept ImportError:\n    resource = None\n\n# 资源限制\ntry:\n    resource.setrlimit(resource.RLIMIT_CPU, ({cpu_limit}, {cpu_limit} + 2))\n    resource.setrlimit(resource.RLIMIT_AS, ({mem_limit}, {mem_limit}))\nexcept Exception:\n    pass  # 非 root 可能设置失败, 忽略\n\n# 覆盖内置危险函数\n_original_open = open\ndef safe_open(file, mode=\'r\', *args, **kwargs):\n    """限制文件访问到安全目录"""\n    import os\n    file_path = os.path.abspath(str(file))\n    safe_prefixes = {safe_paths}\n    is_safe = any(file_path.startswith(p) for p in safe_prefixes)\n    # 允许读 /tmp, /var/tmp, /dev/null 等\n    if not is_safe:\n        # 检查是否是相对路径或当前目录\n        if not os.path.isabs(file_path):\n            is_safe = True\n        else:\n            raise PermissionError(f"文件访问被拒绝: {{file_path}}")\n    return _original_open(file, mode, *args, **kwargs)\n\n# 沙箱环境\n__builtins__ = dict(vars(__builtins__))\n__builtins__[\'open\'] = safe_open\n# 移除危险函数\nfor _danger in [\'exec\', \'eval\', \'compile\', \'__import__\']:\n    __builtins__.pop(_danger, None)\n\n# 注入安全模块\nimport math\nimport json as _json_mod\nimport re\nimport collections\nimport itertools\nimport functools\nimport random\nimport datetime\nimport statistics\nimport hashlib\nimport uuid as _uuid_mod\nimport csv\nimport io\nimport textwrap\nimport string\nimport copy\nimport enum\n\nsafe_builtins = {{\n    \'True\': True, \'False\': False, \'None\': None,\n    \'abs\': abs, \'all\': all, \'any\': any, \'bin\': bin,\n    \'bool\': bool, \'bytes\': bytes, \'callable\': callable,\n    \'chr\': chr, \'dict\': dict, \'dir\': dir, \'divmod\': divmod,\n    \'enumerate\': enumerate, \'filter\': filter, \'float\': float,\n    \'format\': format, \'frozenset\': frozenset, \'getattr\': getattr,\n    \'hasattr\': hasattr, \'hash\': hash, \'hex\': hex, \'id\': id,\n    \'input\': input, \'int\': int, \'isinstance\': isinstance,\n    \'issubclass\': issubclass, \'iter\': iter, \'len\': len,\n    \'list\': list, \'map\': map, \'max\': max, \'min\': min,\n    \'next\': next, \'object\': object, \'oct\': oct, \'ord\': ord,\n    \'pow\': pow, \'print\': print, \'property\': property,\n    \'range\': range, \'repr\': repr, \'reversed\': reversed,\n    \'round\': round, \'set\': set, \'slice\': slice, \'sorted\': sorted,\n    \'str\': str, \'sum\': sum, \'super\': super, \'tuple\': tuple,\n    \'type\': type, \'vars\': vars, \'zip\': zip,\n    # 安全模块\n    \'math\': math, \'json\': _json_mod, \'re\': re,\n    \'datetime\': datetime, \'random\': random, \'statistics\': statistics,\n    \'hashlib\': hashlib, \'uuid\': _uuid_mod, \'csv\': csv,\n    \'io\': io, \'textwrap\': textwrap, \'string\': string,\n    \'copy\': copy, \'enum\': enum, \'collections\': collections,\n    \'itertools\': itertools, \'functools\': functools,\n    \'open\': safe_open,\n}}\n\n# 捕获输出\nfrom io import StringIO\n_stdout = StringIO()\n_stderr = StringIO()\nsys.stdout = _stdout\nsys.stderr = _stderr\n\nstart_time = time.time()\nexit_code = 0\nerror_info = ""\n\ntry:\n    exec(compile({code!r}, \'<sandbox>\', \'exec\'), safe_builtins)\nexcept SystemExit as e:\n    exit_code = e.code if isinstance(e.code, int) else 1\nexcept Exception as e:\n    exit_code = 1\n    error_info = traceback.format_exc()\nfinally:\n    duration = (time.time() - start_time) * 1000\n\n# 收集输出\nstdout_text = _stdout.getvalue()\nstderr_text = _stderr.getvalue() + error_info\n\n# 内存使用 (近似)\npeak_mem = 0.0\ntry:\n    import tracemalloc\n    if tracemalloc.is_tracing():\n        _, peak = tracemalloc.get_traced_memory()\n        peak_mem = peak / (1024 * 1024)\nexcept Exception:\n    pass\n\nresult = {{\n    "exit_code": exit_code,\n    "stdout": stdout_text,\n    "stderr": stderr_text,\n    "duration_ms": duration,\n    "peak_memory_mb": peak_mem,\n}}\n\nsys.stdout = sys.__stdout__\nsys.stderr = sys.__stderr__\nprint(json.dumps(result))\n'
class Sandbox:
    """安全代码执行沙箱"""
    def __init__(self, default_timeout: float = 30.0, max_timeout: float = 300.0, python_cpu_limit: int = 30, python_mem_limit: int = 512 * 1024 * 1024, bash_timeout: float = 60.0, bash_mem_limit: int = 256 * 1024 * 1024, max_output_bytes: int = 10 * 1024 * 1024, safe_dirs: List[str] = None, timeout: float = None, confirm_fn: Optional[Callable[[str], bool]] = None):
        raise NotImplementedError("meshctx-core required (private repo)")

    def run_python(self, code: str, timeout: float = None):
        """同步执行 Python 代码（backward-compat）"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def run_bash(self, code: str, timeout: float = None):
        """同步执行 Bash 命令（backward-compat）"""
        raise NotImplementedError("meshctx-core required (private repo)")

    async def execute(self, code: str, mode: str = 'python', timeout: float = None, env: Dict[str, str] = None, working_dir: str = None) -> ExecutionResult:
        """在沙箱中执行代码"""
        raise NotImplementedError("meshctx-core required (private repo)")

    async def _execute_python(self, execution_id: str, code: str, timeout: float, code_truncated: str) -> ExecutionResult:
        """在子进程中执行 Python 代码"""
        raise NotImplementedError("meshctx-core required (private repo)")

    async def _execute_bash(self, execution_id: str, code: str, timeout: float, code_truncated: str, env: Dict[str, str] = None, working_dir: str = None) -> ExecutionResult:
        """在受限的子进程中执行 Bash 命令"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def _record(self, result: ExecutionResult, **kw):
        """记录执行结果到统计和历史"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def get_sandbox_stats(self, **kw) -> Dict:
        """获取沙箱统计信息"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def get_history(self, limit: int = 20, **kw) -> List[Dict]:
        """获取执行历史"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def clear_history(self, **kw):
        """清空执行历史"""
        raise NotImplementedError("meshctx-core required (private repo)")

    def reset_stats(self, **kw):
        """重置统计信息"""
        raise NotImplementedError("meshctx-core required (private repo)")


class InlineSandbox:
    """内联沙箱 — 不创建子进程, 在同一进程中评估简单表达式"""
    SAFE_BUILTINS = {'True': True, 'False': False, 'None': None, 'abs': abs, 'all': all, 'any': any, 'bin': bin, 'bool': bool, 'bytes': bytes, 'chr': chr, 'complex': complex, 'dict': dict, 'divmod': divmod, 'enumerate': enumerate, 'filter': filter, 'float': float, 'format': format, 'frozenset': frozenset, 'hex': hex, 'int': int, 'isinstance': isinstance, 'len': len, 'list': list, 'map': map, 'max': max, 'min': min, 'oct': oct, 'ord': ord, 'pow': pow, 'range': range, 'repr': repr, 'reversed': reversed, 'round': round, 'set': set, 'slice': slice, 'sorted': sorted, 'str': str, 'sum': sum, 'tuple': tuple, 'type': type, 'zip': zip, 'hash': hash, 'math': __import__('math')}
    def eval(cls, expression: str, context: Dict = None, **kw) -> Tuple[Any, str]:
        """安全地评估简单表达式"""
        raise NotImplementedError("meshctx-core required (private repo)")


class SandboxPlugin:
    """meshctx Plugin 适配器"""
    info = "info"
    state = 'inactive'
    def __init__(self, **kw):
        raise NotImplementedError("meshctx-core required (private repo)")

    async def on_load(self, kernel) -> bool:
        raise NotImplementedError("meshctx-core required (private repo)")

    async def on_unload(self, kernel) -> bool:
        raise NotImplementedError("meshctx-core required (private repo)")

    def generate_report(self, **kw) -> Dict:
        raise NotImplementedError("meshctx-core required (private repo)")


def get_sandbox() -> Sandbox:
    """获取 Sandbox 全局实例，自动创建"""
    raise NotImplementedError("meshctx-core required (private repo)")

def init_sandbox(default_timeout: float = 30.0, max_timeout: float = 300.0, python_mem_limit: int = 512 * 1024 * 1024) -> Sandbox:
    """初始化 Sandbox 全局单例"""
    raise NotImplementedError("meshctx-core required (private repo)")

CodeSandboxV2 = "CodeSandboxV2"
SandboxResult = "SandboxResult"

__all__ = ["ExecutionStatus", "ExecutionResult", "exit_code", "output", "error", "to_dict", "is_success", "CodeScanner", "scan_python", "scan_bash", "Sandbox", "run_python", "run_bash", "execute", "get_sandbox_stats", "get_history", "clear_history", "reset_stats", "InlineSandbox", "eval", "SandboxPlugin", "on_load", "on_unload", "generate_report", "get_sandbox", "init_sandbox"]
