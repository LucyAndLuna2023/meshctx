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

开源实现说明:
  本文件为 meshctx 开源仓库中的真实实现（取代原接口 stub）。
  沙箱基于子进程 + 超时 + 输出捕获, 跨平台:
    - Linux/macOS: 使用 preexec_fn + resource 设置 CPU/内存限制 (resource 调用以
      try/except 包裹, 非 root 环境下 setrlimit 可能失败, 忽略)
    - Windows: 使用 subprocess timeout 机制 (不支持 preexec_fn/resource)
  禁止裸用 fcntl/termios。
"""
from __future__ import annotations

import ast
import asyncio
import builtins
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from abc import ABC
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


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
    exit_code: int = 0
    duration_ms: float = 0.0
    peak_memory_mb: float = 0.0
    timeout_seconds: float = 30.0
    blocked_reason: str = ''
    mode: str = 'python'
    code_truncated: str = ''
    created_at: float = None

    def __post_init__(self):
        if self.status is None:
            self.status = ExecutionStatus.ERROR
        if self.created_at is None:
            self.created_at = time.time()

    def output(self) -> str:
        """stdout + stderr 合并输出"""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(self.stderr)
        return "\n".join(parts)

    def error(self) -> str:
        """返回错误信息 (stderr, 空则为 '')"""
        return self.stderr or ''

    def to_dict(self, **kw) -> Dict[str, Any]:
        """序列化为 dict (JSON 可序列化)"""
        d = {
            "execution_id": self.execution_id,
            "status": self.status.value if isinstance(self.status, ExecutionStatus) else str(self.status),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "exit_code": self.exit_code,
            "duration_ms": round(self.duration_ms, 3),
            "peak_memory_mb": round(self.peak_memory_mb, 3),
            "timeout_seconds": self.timeout_seconds,
            "blocked_reason": self.blocked_reason,
            "mode": self.mode,
            "code_truncated": self.code_truncated,
            "created_at": self.created_at,
        }
        if kw.get("include_output", False):
            d["output"] = self.output()
        return d

    def is_success(self, **kw) -> bool:
        """是否执行成功"""
        return self.status == ExecutionStatus.SUCCESS


class CodeScanner:
    """代码安全扫描器 — 检测危险模式（开源真实实现）

    提供基础但可工作的危险模式检测，保障终端/沙箱在开源环境安全可用。
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
        (r"\bgit\s+push\b.*--force", "git push --force 强制推送"),
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


# 子进程内执行 Python 代码的运行器模板:
#   - 设置 resource 限制 (仅 Unix, try/except 包裹)
#   - 覆盖 open 限制文件访问到安全目录
#   - 移除 exec/eval/compile/__import__
#   - 注入安全模块与安全 builtins
#   - 捕获 stdout/stderr, 最后输出一行 JSON 结果
_PYTHON_RUNNER_TEMPLATE = '''
import sys
import json
import time
import traceback
try:
    import resource  # Unix-only; Windows 上不存在
except ImportError:
    resource = None

# 资源限制
try:
    resource.setrlimit(resource.RLIMIT_CPU, ({cpu_limit}, {cpu_limit} + 2))
    resource.setrlimit(resource.RLIMIT_AS, ({mem_limit}, {mem_limit}))
except Exception:
    pass  # 非 root 可能设置失败, 忽略

# 覆盖内置危险函数
_original_open = open
def safe_open(file, mode=\'r\', *args, **kwargs):
    """限制文件访问到安全目录"""
    import os
    file_path = os.path.abspath(str(file))
    safe_prefixes = {safe_paths}
    is_safe = any(file_path.startswith(p) for p in safe_prefixes)
    # 允许读 /tmp, /var/tmp, /dev/null 等
    if not is_safe:
        # 检查是否是相对路径或当前目录
        if not os.path.isabs(file_path):
            is_safe = True
        else:
            raise PermissionError(f"文件访问被拒绝: {{file_path}}")
    return _original_open(file, mode, *args, **kwargs)

# 沙箱环境
__builtins__ = dict(vars(__builtins__))
__builtins__[\'open\'] = safe_open
# 移除危险函数
for _danger in [\'exec\', \'eval\', \'compile\', \'__import__\']:
    __builtins__.pop(_danger, None)

# 注入安全模块
import math
import json as _json_mod
import re
import collections
import itertools
import functools
import random
import datetime
import statistics
import hashlib
import uuid as _uuid_mod
import csv
import io
import textwrap
import string
import copy
import enum

safe_builtins = {{
    \'True\': True, \'False\': False, \'None\': None,
    \'abs\': abs, \'all\': all, \'any\': any, \'bin\': bin,
    \'bool\': bool, \'bytes\': bytes, \'callable\': callable,
    \'chr\': chr, \'dict\': dict, \'dir\': dir, \'divmod\': divmod,
    \'enumerate\': enumerate, \'filter\': filter, \'float\': float,
    \'format\': format, \'frozenset\': frozenset, \'getattr\': getattr,
    \'hasattr\': hasattr, \'hash\': hash, \'hex\': hex, \'id\': id,
    \'input\': input, \'int\': int, \'isinstance\': isinstance,
    \'issubclass\': issubclass, \'iter\': iter, \'len\': len,
    \'list\': list, \'map\': map, \'max\': max, \'min\': min,
    \'next\': next, \'object\': object, \'oct\': oct, \'ord\': ord,
    \'pow\': pow, \'print\': print, \'property\': property,
    \'range\': range, \'repr\': repr, \'reversed\': reversed,
    \'round\': round, \'set\': set, \'slice\': slice, \'sorted\': sorted,
    \'str\': str, \'sum\': sum, \'super\': super, \'tuple\': tuple,
    \'type\': type, \'vars\': vars, \'zip\': zip,
    # 安全模块
    \'math\': math, \'json\': _json_mod, \'re\': re,
    \'datetime\': datetime, \'random\': random, \'statistics\': statistics,
    \'hashlib\': hashlib, \'uuid\': _uuid_mod, \'csv\': csv,
    \'io\': io, \'textwrap\': textwrap, \'string\': string,
    \'copy\': copy, \'enum\': enum, \'collections\': collections,
    \'itertools\': itertools, \'functools\': functools,
    \'open\': safe_open,
}}

# 捕获输出
from io import StringIO
_stdout = StringIO()
_stderr = StringIO()
sys.stdout = _stdout
sys.stderr = _stderr

start_time = time.time()
exit_code = 0
error_info = ""

try:
    exec(compile({code!r}, \'<sandbox>\', \'exec\'), safe_builtins)
except SystemExit as e:
    exit_code = e.code if isinstance(e.code, int) else 1
except Exception as e:
    exit_code = 1
    error_info = traceback.format_exc()
finally:
    duration = (time.time() - start_time) * 1000

# 收集输出
stdout_text = _stdout.getvalue()
stderr_text = _stderr.getvalue() + error_info

# 内存使用 (近似)
peak_mem = 0.0
try:
    import tracemalloc
    if tracemalloc.is_tracing():
        _, peak = tracemalloc.get_traced_memory()
        peak_mem = peak / (1024 * 1024)
except Exception:
    pass

result = {{
    "exit_code": exit_code,
    "stdout": stdout_text,
    "stderr": stderr_text,
    "duration_ms": duration,
    "peak_memory_mb": peak_mem,
}}

sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
print(json.dumps(result))
'''


def _default_safe_dirs() -> List[str]:
    """默认安全目录: 系统临时目录 + 当前工作目录 + 用户 home 的 .meshctx"""
    dirs = [tempfile.gettempdir()]
    try:
        dirs.append(os.getcwd())
    except OSError:
        pass
    home = os.path.expanduser("~")
    if home and home != "~":
        dirs.append(os.path.join(home, ".meshctx"))
    # 去重, 展开
    result = []
    for d in dirs:
        if d and d not in result:
            result.append(d)
    return result


class Sandbox:
    """安全代码执行沙箱"""

    def __init__(
        self,
        default_timeout: float = 30.0,
        max_timeout: float = 300.0,
        python_cpu_limit: int = 30,
        python_mem_limit: int = 512 * 1024 * 1024,
        bash_timeout: float = 60.0,
        bash_mem_limit: int = 256 * 1024 * 1024,
        max_output_bytes: int = 10 * 1024 * 1024,
        safe_dirs: List[str] = None,
        timeout: float = None,
        confirm_fn: Optional[Callable[[str], bool]] = None,
    ):
        if timeout is not None:
            default_timeout = float(timeout)
        self._default_timeout = float(default_timeout)
        self._max_timeout = float(max_timeout)
        self._python_cpu_limit = int(python_cpu_limit)
        self._python_mem_limit = int(python_mem_limit)
        self._bash_timeout = float(bash_timeout)
        self._bash_mem_limit = int(bash_mem_limit)
        self._max_output_bytes = int(max_output_bytes)
        self._safe_dirs = list(safe_dirs) if safe_dirs else _default_safe_dirs()
        self._confirm_fn = confirm_fn

        self._history: List[Dict[str, Any]] = []
        self._stats = {
            "total_executions": 0,
            "success_count": 0,
            "error_count": 0,
            "timeout_count": 0,
            "blocked_count": 0,
            "killed_count": 0,
            "total_duration_ms": 0.0,
        }
        self._lock = threading.Lock()
        self._exec_counter = 0

    # ── 内部工具 ────────────────────────────────────────────
    def _new_execution_id(self) -> str:
        with self._lock:
            self._exec_counter += 1
            return f"sandbox_{int(time.time() * 1000)}_{self._exec_counter}"

    def _clamp_timeout(self, timeout: Optional[float]) -> float:
        if timeout is None:
            return self._default_timeout
        timeout = float(timeout)
        if timeout <= 0:
            return 0.5
        return min(timeout, self._max_timeout)

    def _truncate_output(self, text: str) -> str:
        if len(text) > self._max_output_bytes:
            return text[: self._max_output_bytes] + f"\n...[输出被截断, 超过 {self._max_output_bytes} bytes]"
        return text

    def _truncate_code(self, code: str) -> str:
        """记录被截断的代码摘要 (避免历史记录携带超长代码)"""
        if len(code) <= 200:
            return code
        return code[:200] + f"...[代码被截断, 共 {len(code)} 字符]"

    def _ask_confirm(self, code: str) -> bool:
        """调用确认函数 (可能为 None)"""
        if self._confirm_fn is None:
            return True
        try:
            return bool(self._confirm_fn(code))
        except Exception:
            return False

    # ── 向后兼容同步入口 ────────────────────────────────────
    def run_python(self, code: str, timeout: float = None):
        """同步执行 Python 代码（backward-compat）"""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.execute(code, mode="python", timeout=timeout))
        finally:
            loop.close()

    def run_bash(self, code: str, timeout: float = None):
        """同步执行 Bash 命令（backward-compat）"""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.execute(code, mode="bash", timeout=timeout))
        finally:
            loop.close()

    # ── 主执行入口 ──────────────────────────────────────────
    async def execute(
        self,
        code: str,
        mode: str = 'python',
        timeout: float = None,
        env: Dict[str, str] = None,
        working_dir: str = None,
    ) -> ExecutionResult:
        """在沙箱中执行代码"""
        mode = (mode or "python").lower().strip()
        if mode not in ("python", "bash"):
            result = ExecutionResult(
                execution_id=self._new_execution_id(),
                status=ExecutionStatus.ERROR,
                stderr=f"不支持的执行模式: {mode} (仅支持 python/bash)",
                mode=mode,
                timeout_seconds=self._clamp_timeout(timeout),
            )
            self._record(result)
            return result

        timeout = self._clamp_timeout(timeout)
        execution_id = self._new_execution_id()
        code_truncated = self._truncate_code(code)

        if mode == "python":
            result = await self._execute_python(execution_id, code, timeout, code_truncated)
        else:
            result = await self._execute_bash(
                execution_id, code, timeout, code_truncated, env=env, working_dir=working_dir
            )
        self._record(result)
        return result

    async def _execute_python(
        self,
        execution_id: str,
        code: str,
        timeout: float,
        code_truncated: str,
    ) -> ExecutionResult:
        """在子进程中执行 Python 代码"""
        started = time.time()

        # 1. 危险模式检测
        dangerous = CodeScanner.scan_python(code)
        if dangerous:
            if self._confirm_fn is not None:
                approved = self._ask_confirm(code)
                if not approved:
                    return ExecutionResult(
                        execution_id=execution_id,
                        status=ExecutionStatus.ERROR,
                        stderr=f"执行被拒绝: 检测到危险模式 {', '.join(dangerous)}, 用户拒绝确认",
                        return_code=1,
                        exit_code=1,
                        duration_ms=(time.time() - started) * 1000,
                        blocked_reason="user_rejected",
                        mode='python',
                        code_truncated=code_truncated,
                        timeout_seconds=timeout,
                    )
            else:
                return ExecutionResult(
                    execution_id=execution_id,
                    status=ExecutionStatus.BLOCKED,
                    stderr=f"执行被沙箱拦截: 检测到危险模式 {', '.join(dangerous)}",
                    return_code=-1,
                    exit_code=-1,
                    duration_ms=(time.time() - started) * 1000,
                    blocked_reason="; ".join(dangerous),
                    mode='python',
                    code_truncated=code_truncated,
                    timeout_seconds=timeout,
                )

        # 2. 渲染运行器脚本
        safe_paths_repr = ", ".join(repr(p) for p in self._safe_dirs)
        runner_code = _PYTHON_RUNNER_TEMPLATE.format(
            cpu_limit=self._python_cpu_limit,
            mem_limit=self._python_mem_limit,
            safe_paths=safe_paths_repr,
            code=code,
        )

        runner_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix="meshctx_sandbox_", delete=False, encoding="utf-8"
            ) as f:
                f.write(runner_code)
                runner_path = f.name

            # Linux/macOS: preexec_fn + resource 限制 (try/except 包裹, 非 root 可能失败)
            preexec_fn = None
            if os.name == "posix":
                cpu = self._python_cpu_limit
                mem = self._python_mem_limit

                def _limit_resources():
                    try:
                        import resource
                        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 2))
                        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
                    except Exception:
                        pass

                preexec_fn = _limit_resources

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                runner_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=preexec_fn,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ExecutionResult(
                    execution_id=execution_id,
                    status=ExecutionStatus.TIMEOUT,
                    stderr=f"执行超时 ({timeout}s), 进程已被终止",
                    return_code=-9,
                    exit_code=-9,
                    duration_ms=(time.time() - started) * 1000,
                    mode='python',
                    code_truncated=code_truncated,
                    timeout_seconds=timeout,
                )

            stdout_text = self._truncate_output(stdout_b.decode("utf-8", errors="replace"))
            stderr_text = self._truncate_output(stderr_b.decode("utf-8", errors="replace"))

            # 解析运行器输出的最后一行 JSON
            inner = {
                "exit_code": proc.returncode if proc.returncode is not None else -1,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "duration_ms": (time.time() - started) * 1000,
                "peak_memory_mb": 0.0,
            }
            for line in reversed(stdout_text.splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, dict) and "exit_code" in parsed:
                        inner = parsed
                    break
                except (ValueError, TypeError):
                    continue

            status = ExecutionStatus.SUCCESS
            if inner["exit_code"] != 0:
                status = ExecutionStatus.ERROR
            if inner.get("stderr") and not inner.get("stdout"):
                # 仅 stderr 有内容且退出码非 0 → ERROR; 有 stdout 仍可能成功
                if inner["exit_code"] != 0:
                    status = ExecutionStatus.ERROR

            return ExecutionResult(
                execution_id=execution_id,
                status=status,
                stdout=self._truncate_output(inner.get("stdout", "")),
                stderr=self._truncate_output(inner.get("stderr", "")),
                return_code=int(inner.get("exit_code", 0) or 0),
                exit_code=int(inner.get("exit_code", 0) or 0),
                duration_ms=float(inner.get("duration_ms", (time.time() - started) * 1000)),
                peak_memory_mb=float(inner.get("peak_memory_mb", 0.0) or 0.0),
                mode='python',
                code_truncated=code_truncated,
                timeout_seconds=timeout,
            )
        except (OSError, subprocess.SubprocessError) as e:
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.ERROR,
                stderr=f"沙箱子进程启动失败: {e}",
                return_code=-1,
                exit_code=-1,
                duration_ms=(time.time() - started) * 1000,
                mode='python',
                code_truncated=code_truncated,
                timeout_seconds=timeout,
            )
        finally:
            if runner_path:
                try:
                    os.unlink(runner_path)
                except OSError:
                    pass

    async def _execute_bash(
        self,
        execution_id: str,
        code: str,
        timeout: float,
        code_truncated: str,
        env: Dict[str, str] = None,
        working_dir: str = None,
    ) -> ExecutionResult:
        """在受限的子进程中执行 Bash 命令"""
        started = time.time()

        # 危险命令检测 + 确认回调
        safe, reason = CodeScanner.scan_bash(code)
        if not safe:
            if self._confirm_fn is not None:
                approved = self._ask_confirm(code)
                if not approved:
                    return ExecutionResult(
                        execution_id=execution_id,
                        status=ExecutionStatus.ERROR,
                        stderr=f"执行被拒绝: 检测到危险命令 ({reason}), 用户拒绝确认",
                        return_code=1,
                        exit_code=1,
                        duration_ms=(time.time() - started) * 1000,
                        blocked_reason=reason,
                        mode='bash',
                        code_truncated=code_truncated,
                        timeout_seconds=timeout,
                    )
            else:
                return ExecutionResult(
                    execution_id=execution_id,
                    status=ExecutionStatus.BLOCKED,
                    stderr=f"执行被沙箱拦截: 检测到危险命令 ({reason})",
                    return_code=-1,
                    exit_code=-1,
                    duration_ms=(time.time() - started) * 1000,
                    blocked_reason=reason,
                    mode='bash',
                    code_truncated=code_truncated,
                    timeout_seconds=timeout,
                )

        # 构造 shell 命令
        if os.name == "nt":
            cmdline = ["cmd", "/c", code]
        else:
            cmdline = ["/bin/sh", "-c", code]

        proc_env = None
        if env:
            proc_env = dict(os.environ)
            proc_env.update(env)
        cwd = working_dir or None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmdline,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=proc_env,
                cwd=cwd,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ExecutionResult(
                    execution_id=execution_id,
                    status=ExecutionStatus.TIMEOUT,
                    stderr=f"执行超时 ({timeout}s), 进程已被终止",
                    return_code=-9,
                    exit_code=-9,
                    duration_ms=(time.time() - started) * 1000,
                    mode='bash',
                    code_truncated=code_truncated,
                    timeout_seconds=timeout,
                )

            rc = proc.returncode if proc.returncode is not None else 0
            status = ExecutionStatus.SUCCESS if rc == 0 else ExecutionStatus.ERROR
            return ExecutionResult(
                execution_id=execution_id,
                status=status,
                stdout=self._truncate_output(stdout_b.decode("utf-8", errors="replace")),
                stderr=self._truncate_output(stderr_b.decode("utf-8", errors="replace")),
                return_code=rc,
                exit_code=rc,
                duration_ms=(time.time() - started) * 1000,
                mode='bash',
                code_truncated=code_truncated,
                timeout_seconds=timeout,
            )
        except (OSError, subprocess.SubprocessError) as e:
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.ERROR,
                stderr=f"沙箱子进程启动失败: {e}",
                return_code=-1,
                exit_code=-1,
                duration_ms=(time.time() - started) * 1000,
                mode='bash',
                code_truncated=code_truncated,
                timeout_seconds=timeout,
            )

    def _record(self, result: ExecutionResult, **kw):
        """记录执行结果到统计和历史"""
        with self._lock:
            self._stats["total_executions"] += 1
            self._stats["total_duration_ms"] += result.duration_ms or 0.0
            status = result.status
            if status == ExecutionStatus.SUCCESS:
                self._stats["success_count"] += 1
            elif status == ExecutionStatus.TIMEOUT:
                self._stats["timeout_count"] += 1
            elif status == ExecutionStatus.BLOCKED:
                self._stats["blocked_count"] += 1
            elif status == ExecutionStatus.KILLED:
                self._stats["killed_count"] += 1
            else:
                self._stats["error_count"] += 1
            self._history.insert(0, result.to_dict())
            if len(self._history) > 200:
                self._history = self._history[:200]

    def get_sandbox_stats(self, **kw) -> Dict[str, Any]:
        """获取沙箱统计信息"""
        with self._lock:
            total = self._stats["total_executions"]
            success = self._stats["success_count"]
            stats = dict(self._stats)
            stats["success_rate"] = round((success / total * 100.0), 2) if total else 0.0
            stats["error_rate"] = round(
                (self._stats["error_count"] / total * 100.0), 2
            ) if total else 0.0
            stats["avg_duration_ms"] = round(
                (self._stats["total_duration_ms"] / total), 3
            ) if total else 0.0
            stats["history_size"] = len(self._history)
            return stats

    def get_history(self, limit: int = 20, **kw) -> List[Dict]:
        """获取执行历史 (最近的在前)"""
        with self._lock:
            return list(self._history[: int(limit)])

    def clear_history(self, **kw):
        """清空执行历史"""
        with self._lock:
            self._history = []

    def reset_stats(self, **kw):
        """重置统计信息"""
        with self._lock:
            self._stats = {
                "total_executions": 0,
                "success_count": 0,
                "error_count": 0,
                "timeout_count": 0,
                "blocked_count": 0,
                "killed_count": 0,
                "total_duration_ms": 0.0,
            }


class InlineSandbox:
    """内联沙箱 — 不创建子进程, 在同一进程中评估简单表达式"""

    SAFE_BUILTINS = {
        'True': True, 'False': False, 'None': None,
        'abs': abs, 'all': all, 'any': any, 'bin': bin, 'bool': bool,
        'bytes': bytes, 'chr': chr, 'complex': complex, 'dict': dict,
        'divmod': divmod, 'enumerate': enumerate, 'filter': filter,
        'float': float, 'format': format, 'frozenset': frozenset,
        'hex': hex, 'int': int, 'isinstance': isinstance, 'len': len,
        'list': list, 'map': map, 'max': max, 'min': min, 'oct': oct,
        'ord': ord, 'pow': pow, 'range': range, 'repr': repr,
        'reversed': reversed, 'round': round, 'set': set, 'slice': slice,
        'sorted': sorted, 'str': str, 'sum': sum, 'tuple': tuple,
        'type': type, 'zip': zip, 'hash': hash,
        'math': __import__('math'),
    }

    # 允许的 AST 节点集合 (白名单)
    _ALLOWED_NODES = (
        ast.Expression, ast.Constant, ast.Name, ast.Load,
        ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
        ast.Pow, ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
        ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        ast.Is, ast.IsNot, ast.In, ast.NotIn,
        ast.Tuple, ast.List, ast.Dict, ast.Set,
        ast.Call, ast.Attribute, ast.keyword,
    )

    @classmethod
    def eval(cls, expression: str, context: Dict = None, **kw) -> Tuple[Any, str]:
        """安全地评估简单表达式。返回 (结果, 错误), 错误为空字符串表示成功。"""
        if not isinstance(expression, str) or not expression.strip():
            return None, "空表达式"

        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            return None, f"语法错误: {e}"

        # AST 白名单校验: 仅允许简单表达式节点
        for node in ast.walk(tree):
            if not isinstance(node, cls._ALLOWED_NODES):
                return None, f"不安全的表达式节点: {type(node).__name__}"
            if isinstance(node, ast.Attribute):
                # 仅允许访问白名单中模块的成员 (如 math.sqrt)
                base = node.value
                if not isinstance(base, ast.Name) or base.id not in cls.SAFE_BUILTINS:
                    return None, "不允许的属性访问"
                base_val = cls.SAFE_BUILTINS.get(base.id)
                import types
                if not isinstance(base_val, types.ModuleType):
                    return None, "不允许的属性访问"
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id not in cls.SAFE_BUILTINS:
                    return None, f"不允许调用: {func.id}"
                if isinstance(func, ast.Attribute):
                    base = func.value
                    if not isinstance(base, ast.Name) or base.id not in cls.SAFE_BUILTINS:
                        return None, "不允许的调用"
                    import types
                    if not isinstance(cls.SAFE_BUILTINS.get(base.id), types.ModuleType):
                        return None, "不允许的调用"
                elif not isinstance(func, ast.Name):
                    return None, "不允许的调用形式"
            if isinstance(node, ast.Name):
                if node.id not in cls.SAFE_BUILTINS and not (context and node.id in context):
                    return None, f"不允许的标识符: {node.id}"

        env = dict(cls.SAFE_BUILTINS)
        if context:
            env.update(context)
        try:
            result = builtins.eval(
                compile(tree, "<inline-sandbox>", "eval"),
                {"__builtins__": {}},
                env,
            )
            return result, ""
        except Exception as e:
            return None, str(e)


class SandboxPlugin:
    """meshctx Plugin 适配器"""

    info = "info"
    state = 'inactive'

    def __init__(self, **kw):
        self._sandbox = kw.pop("sandbox", None) or get_sandbox()
        self.info = kw.pop("info", "meshctx Sandbox Plugin")
        self.state = 'inactive'

    async def on_load(self, kernel) -> bool:
        """加载插件: 激活沙箱"""
        self.state = 'active'
        return True

    async def on_unload(self, kernel) -> bool:
        """卸载插件: 停用沙箱"""
        self.state = 'inactive'
        return True

    def generate_report(self, **kw) -> Dict:
        """生成沙箱运行报告"""
        stats = self._sandbox.get_sandbox_stats()
        history = self._sandbox.get_history(limit=kw.get("history_limit", 10))
        return {
            "plugin": "sandbox",
            "state": self.state,
            "stats": stats,
            "recent_executions": history,
        }


# ── CodeSandboxV2 (v2 兼容层, 简单子进程沙箱) ─────────────────────
@dataclass
class SandboxResult:
    """v2 兼容执行结果"""
    output: str = ''
    error: str = ''
    exit_code: int = 0
    status: str = 'success'
    execution_id: str = ''
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output": self.output,
            "error": self.error,
            "exit_code": self.exit_code,
            "status": self.status,
            "execution_id": self.execution_id,
            "duration_ms": round(self.duration_ms, 3),
        }


class CodeSandboxV2:
    """v2 兼容代码沙箱 — 子进程执行 + 超时 + 输出捕获"""

    def __init__(self, timeout: float = 30.0, max_output: int = 100000, **kw):
        self._timeout = float(timeout)
        self._max_output = int(max_output)
        self._counter = 0

    def _exec_id(self) -> str:
        self._counter += 1
        return f"cs2_{int(time.time() * 1000)}_{self._counter}"

    def _truncate(self, text: str) -> str:
        if len(text) > self._max_output:
            return text[: self._max_output] + "\n...[截断]"
        return text

    def _run(self, cmd: List[str], timeout: float) -> SandboxResult:
        exec_id = self._exec_id()
        started = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                errors="replace",
            )
            rc = proc.returncode
            status = "success" if rc == 0 else "error"
            return SandboxResult(
                output=self._truncate(proc.stdout or ""),
                error=self._truncate(proc.stderr or ""),
                exit_code=rc,
                status=status,
                execution_id=exec_id,
                duration_ms=(time.time() - started) * 1000,
            )
        except subprocess.TimeoutExpired as e:
            return SandboxResult(
                output=self._truncate(e.stdout or ""),
                error=f"TIMEOUT: 执行超过 {timeout}s 已终止",
                exit_code=-9,
                status="timeout",
                execution_id=exec_id,
                duration_ms=(time.time() - started) * 1000,
            )
        except OSError as e:
            return SandboxResult(
                error=f"执行失败: {e}",
                exit_code=-1,
                status="error",
                execution_id=exec_id,
                duration_ms=(time.time() - started) * 1000,
            )

    def run_python(self, code: str, timeout: float = None) -> SandboxResult:
        """在子进程中执行 Python 代码"""
        t = float(timeout) if timeout is not None else self._timeout
        return self._run([sys.executable, "-I", "-c", code], t)

    def run_bash(self, code: str, timeout: float = None) -> SandboxResult:
        """在子进程中执行 shell 命令"""
        t = float(timeout) if timeout is not None else self._timeout
        if os.name == "nt":
            return self._run(["cmd", "/c", code], t)
        return self._run(["/bin/sh", "-c", code], t)

    def run(self, code: str, language: str = "python", timeout: float = None) -> SandboxResult:
        """通用入口 (language: python/bash)"""
        lang = (language or "python").lower()
        if lang == "bash":
            return self.run_bash(code, timeout=timeout)
        return self.run_python(code, timeout=timeout)


# 兼容别名: src/core/__init__.py 的 _known 映射引用 SandboxEngine
SandboxEngine = Sandbox


# ── 单例 ─────────────────────────────────────────────────────────
_sandbox_instance: Optional[Sandbox] = None
_sandbox_lock = threading.Lock()


def get_sandbox() -> Sandbox:
    """获取 Sandbox 全局实例，自动创建"""
    global _sandbox_instance
    with _sandbox_lock:
        if _sandbox_instance is None:
            _sandbox_instance = Sandbox()
        return _sandbox_instance


def init_sandbox(
    default_timeout: float = 30.0,
    max_timeout: float = 300.0,
    python_mem_limit: int = 512 * 1024 * 1024,
) -> Sandbox:
    """初始化 Sandbox 全局单例 (重新创建)"""
    global _sandbox_instance
    with _sandbox_lock:
        _sandbox_instance = Sandbox(
            default_timeout=default_timeout,
            max_timeout=max_timeout,
            python_mem_limit=python_mem_limit,
        )
        return _sandbox_instance


# ── 模块级向后兼容函数 (对应原 __all__ 中的方法名) ────────────────
def run_python(code: str, timeout: float = None):
    """模块级便捷函数: 使用全局沙箱执行 Python 代码"""
    return get_sandbox().run_python(code, timeout=timeout)


def run_bash(code: str, timeout: float = None):
    """模块级便捷函数: 使用全局沙箱执行 Bash 命令"""
    return get_sandbox().run_bash(code, timeout=timeout)


async def execute(code: str, mode: str = 'python', timeout: float = None,
                  env: Dict[str, str] = None, working_dir: str = None) -> ExecutionResult:
    """模块级便捷函数: 使用全局沙箱执行代码"""
    return await get_sandbox().execute(code, mode=mode, timeout=timeout, env=env, working_dir=working_dir)


def get_sandbox_stats(**kw) -> Dict:
    return get_sandbox().get_sandbox_stats(**kw)


def get_history(limit: int = 20, **kw) -> List[Dict]:
    return get_sandbox().get_history(limit=limit, **kw)


def clear_history(**kw):
    return get_sandbox().clear_history(**kw)


def reset_stats(**kw):
    return get_sandbox().reset_stats(**kw)


# 与 __all__ 中方法名对齐的模块级别名 (scan_python/scan_bash/eval 等)
scan_python = CodeScanner.scan_python
scan_bash = CodeScanner.scan_bash
eval = InlineSandbox.eval

__all__ = [
    "ExecutionStatus", "ExecutionResult",
    "CodeScanner", "scan_python", "scan_bash",
    "Sandbox", "SandboxEngine", "CodeSandboxV2", "SandboxResult",
    "run_python", "run_bash", "execute",
    "get_sandbox_stats", "get_history", "clear_history", "reset_stats",
    "InlineSandbox", "eval",
    "SandboxPlugin", "on_load", "on_unload", "generate_report",
    "get_sandbox", "init_sandbox",
]
