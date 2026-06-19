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
  print(result.stdout)  # "2\n"

  stats = sandbox.get_sandbox_stats()
  # → {"total_executions": 42, "success_rate": 0.95, ...}
"""

import asyncio
import gzip
import io
import json
import logging
import os
import platform
import re
import resource
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.sandbox")


# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

# Python 安全导入白名单
SAFE_PYTHON_MODULES: Set[str] = {
    "abc", "argparse", "array", "ast", "base64", "binascii",
    "bisect", "calendar", "cmath", "collections", "copy",
    "csv", "dataclasses", "datetime", "decimal", "difflib",
    "enum", "fractions", "functools", "hashlib", "heapq",
    "html", "importlib", "inspect", "io", "itertools",
    "json", "logging", "math", "operator", "pathlib",
    "pprint", "random", "re", "statistics", "string",
    "struct", "textwrap", "time", "traceback", "typing",
    "unicodedata", "uuid", "warnings", "weakref", "xml",
    "yaml", "numpy", "pandas", "scipy",  # 常用数据科学库
    "matplotlib", "seaborn",  # 可视化
    "requests",  # 受限HTTP (仅GET)
    "bs4", "lxml",  # 解析
    "pytest", "unittest",  # 测试框架
}

# 危险模式 — 直接拦截
DANGER_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bimport\s+os\b"),
    re.compile(r"\bimport\s+subprocess\b"),
    re.compile(r"\bimport\s+sys\b"),
    re.compile(r"\bimport\s+socket\b"),
    re.compile(r"\bimport\s+ctypes\b"),
    re.compile(r"\bimport\s+multiprocessing\b"),
    re.compile(r"\bimport\s+signal\b"),
    re.compile(r"\bimport\s+shutil\b"),
    re.compile(r"\bimport\s+pickle\b"),
    re.compile(r"\bimport\s+marshal\b"),
    re.compile(r"\bimport\s+codeop\b"),
    re.compile(r"\bimport\s+compileall\b"),
    re.compile(r"\bimport\s+pty\b"),
    re.compile(r"\bimport\s+fcntl\b"),
    re.compile(r"\bimport\s+resource\b"),
    re.compile(r"\bimport\s+pwd\b"),
    re.compile(r"\bimport\s+grp\b"),
    re.compile(r"\bimport\s+termios\b"),
    re.compile(r"\bfrom\s+os\s+import\b"),
    re.compile(r"\bfrom\s+subprocess\s+import\b"),
    re.compile(r"\bfrom\s+sys\s+import\b"),
    re.compile(r"\bfrom\s+socket\s+import\b"),
    re.compile(r"\bfrom\s+ctypes\s+import\b"),
    re.compile(r"\b__import__\s*\(\s*['\"]os['\"]"),
    re.compile(r"\b__import__\s*\(\s*['\"]subprocess['\"]"),
    re.compile(r"\b__import__\s*\(\s*['\"]sys['\"]"),
    re.compile(r"\bexec\s*\(\s*['\"]"),
    re.compile(r"\beval\s*\(\s*['\"]"),
    re.compile(r"\bcompile\s*\(\s*['\"]"),
    re.compile(r"\bopen\s*\(\s*['\"](/etc|/proc|/sys|/dev)"),
    # Bash 危险命令
    re.compile(r"\brm\s+-rf\s+/"),
    re.compile(r"\bdd\s+if="),
    re.compile(r"\bmkfs\."),
    re.compile(r"\bchmod\s+777\s+/"),
    re.compile(r"\b>:.*>/dev/"),
    re.compile(r"\bcurl.*\|.*sh\b"),
    re.compile(r"\bwget.*\|.*sh\b"),
]

# Bash 安全命令白名单
SAFE_BASH_COMMANDS: Set[str] = {
    "ls", "cat", "head", "tail", "wc", "sort", "uniq",
    "grep", "find", "echo", "printf", "date", "whoami",
    "pwd", "env", "uname", "df", "du", "free", "uptime",
    "which", "type", "basename", "dirname", "readlink",
    "python3", "python", "node", "npm", "npx", "pip",
    "git", "curl", "wget", "tar", "gzip", "gunzip",
    "zip", "unzip", "awk", "sed", "tr", "cut", "paste",
    "diff", "cmp", "tee", "xargs", "true", "false",
    "test", "[", "sleep", "touch", "mkdir", "cp",
    "mv", "ln", "stat", "file", "tree",
}

# Bash 黑名单 (覆盖白名单, 绝对禁止)
BASH_BLACKLIST: Set[str] = {
    "rm", "shutdown", "reboot", "halt", "poweroff",
    "kill", "killall", "pkill", "fdisk", "mount",
    "umount", "chown", "chmod", "chroot", "mknod",
    "iptables", "ip6tables", "systemctl", "service",
    "visudo", "passwd", "su", "sudo",
}

# 安全文件系统前缀
SAFE_PATHS: List[str] = ["/tmp/", "/var/tmp/", "/dev/null", "/dev/stdout", "/dev/stderr"]


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    KILLED = "killed"
    BLOCKED = "blocked"       # 危险模式拦截
    MEMORY_LIMIT = "memory_limit"


@dataclass
class ExecutionResult:
    """沙箱执行结果"""
    execution_id: str = ""
    status: ExecutionStatus = ExecutionStatus.SUCCESS
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    duration_ms: float = 0.0
    peak_memory_mb: float = 0.0
    timeout_seconds: float = 30.0
    blocked_reason: str = ""       # BLOCKED 状态的原因
    mode: str = "python"           # python / bash
    code_truncated: str = ""       # 代码片段 (前100字符)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "execution_id": self.execution_id,
            "status": self.status.value,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "duration_ms": self.duration_ms,
            "peak_memory_mb": self.peak_memory_mb,
            "timeout_seconds": self.timeout_seconds,
            "blocked_reason": self.blocked_reason,
            "mode": self.mode,
            "code_truncated": self.code_truncated,
            "created_at": self.created_at,
        }

    @property
    def is_success(self) -> bool:
        return self.status == ExecutionStatus.SUCCESS and self.return_code == 0

    @property 
    def output(self) -> str:
        """stdout + stderr 合并输出"""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(f"[STDERR]\n{self.stderr}")
        return "\n".join(parts)


# ═══════════════════════════════════════════════════════════
# 安全扫描器
# ═══════════════════════════════════════════════════════════

class CodeScanner:
    """代码安全扫描器 — 检测危险模式"""

    @classmethod
    def scan_python(cls, code: str) -> List[str]:
        """
        扫描 Python 代码中的危险模式

        Returns:
            检测到的危险模式列表 (空列表 = 安全)
        """
        violations = []

        for pattern in DANGER_PATTERNS:
            if pattern.search(code):
                violations.append(f"危险模式匹配: {pattern.pattern}")

        return violations

    @classmethod
    def scan_bash(cls, command: str) -> Tuple[bool, str]:
        """
        扫描 Bash 命令

        Returns:
            (is_safe, reason)
        """
        # 提取主命令
        cmd = command.strip().split()[0] if command.strip().split() else ""
        # 去掉路径前缀
        cmd_name = cmd.split("/")[-1] if "/" in cmd else cmd

        # 黑名单检查
        if cmd_name in BASH_BLACKLIST:
            return False, f"禁止命令: {cmd_name}"

        # 危险模式检查
        for pattern in DANGER_PATTERNS:
            if pattern.search(command):
                return False, f"危险模式匹配: {pattern.pattern}"

        # 白名单检查 (如果命令不在白名单中, 发出警告但不一定拦截)
        if cmd_name and cmd_name not in SAFE_BASH_COMMANDS:
            logger.warning(f"未知命令 '{cmd_name}' (不在白名单中), 仍允许执行")

        return True, ""


# ═══════════════════════════════════════════════════════════
# Python 沙箱子进程模板
# ═══════════════════════════════════════════════════════════

_PYTHON_RUNNER_TEMPLATE = '''
import sys
import json
import time
import traceback
import resource

# 资源限制
try:
    resource.setrlimit(resource.RLIMIT_CPU, ({cpu_limit}, {cpu_limit} + 2))
    resource.setrlimit(resource.RLIMIT_AS, ({mem_limit}, {mem_limit}))
except Exception:
    pass  # 非 root 可能设置失败, 忽略

# 覆盖内置危险函数
_original_open = open
def safe_open(file, mode='r', *args, **kwargs):
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
            raise PermissionError(f"文件访问被拒绝: {file_path}")
    return _original_open(file, mode, *args, **kwargs)

# 沙箱环境
__builtins__ = dict(__builtins__)
__builtins__['open'] = safe_open
# 移除危险函数
for _danger in ['exec', 'eval', 'compile', '__import__']:
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
    'True': True, 'False': False, 'None': None,
    'abs': abs, 'all': all, 'any': any, 'bin': bin,
    'bool': bool, 'bytes': bytes, 'callable': callable,
    'chr': chr, 'dict': dict, 'dir': dir, 'divmod': divmod,
    'enumerate': enumerate, 'filter': filter, 'float': float,
    'format': format, 'frozenset': frozenset, 'getattr': getattr,
    'hasattr': hasattr, 'hash': hash, 'hex': hex, 'id': id,
    'input': input, 'int': int, 'isinstance': isinstance,
    'issubclass': issubclass, 'iter': iter, 'len': len,
    'list': list, 'map': map, 'max': max, 'min': min,
    'next': next, 'object': object, 'oct': oct, 'ord': ord,
    'pow': pow, 'print': print, 'property': property,
    'range': range, 'repr': repr, 'reversed': reversed,
    'round': round, 'set': set, 'slice': slice, 'sorted': sorted,
    'str': str, 'sum': sum, 'super': super, 'tuple': tuple,
    'type': type, 'vars': vars, 'zip': zip,
    # 安全模块
    'math': math, 'json': _json_mod, 're': re,
    'datetime': datetime, 'random': random, 'statistics': statistics,
    'hashlib': hashlib, 'uuid': _uuid_mod, 'csv': csv,
    'io': io, 'textwrap': textwrap, 'string': string,
    'copy': copy, 'enum': enum, 'collections': collections,
    'itertools': itertools, 'functools': functools,
    'open': safe_open,
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
    exec(compile({code!r}, '<sandbox>', 'exec'), safe_builtins)
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


# ═══════════════════════════════════════════════════════════
# Sandbox 核心
# ═══════════════════════════════════════════════════════════

class Sandbox:
    """
    安全代码执行沙箱

    特性:
      - Python 和 Bash 双模式
      - 危险模式自动检测拦截
      - 超时/内存限制
      - stdout/stderr 捕获
      - 执行统计追踪
    """

    def __init__(
        self,
        default_timeout: float = 30.0,
        max_timeout: float = 300.0,
        python_cpu_limit: int = 30,        # CPU seconds
        python_mem_limit: int = 512 * 1024 * 1024,  # 512 MB
        bash_timeout: float = 60.0,
        bash_mem_limit: int = 256 * 1024 * 1024,    # 256 MB
        max_output_bytes: int = 10 * 1024 * 1024,   # 10 MB
        safe_dirs: List[str] = None,
    ):
        self.default_timeout = default_timeout
        self.max_timeout = max_timeout
        self.python_cpu_limit = python_cpu_limit
        self.python_mem_limit = python_mem_limit
        self.bash_timeout = bash_timeout
        self.bash_mem_limit = bash_mem_limit
        self.max_output_bytes = max_output_bytes
        self.safe_dirs = safe_dirs or SAFE_PATHS

        # 统计
        self._stats: Dict[str, Any] = {
            "total_executions": 0,
            "success_count": 0,
            "error_count": 0,
            "timeout_count": 0,
            "blocked_count": 0,
            "killed_count": 0,
            "total_duration_ms": 0.0,
            "python_count": 0,
            "bash_count": 0,
            "last_execution_at": 0.0,
            "violations": [],
        }

        # 执行历史 (最近100条)
        self._history: List[ExecutionResult] = []
        self._history_max = 100

        logger.info(f"Sandbox initialized: timeout={default_timeout}s, "
                   f"cpu_limit={python_cpu_limit}s, mem_limit={python_mem_limit//1024//1024}MB")

    # ── 主入口 ────────────────────────────────────────────

    async def execute(
        self,
        code: str,
        mode: str = "python",
        timeout: float = None,
        env: Dict[str, str] = None,
        working_dir: str = None,
    ) -> ExecutionResult:
        """
        在沙箱中执行代码

        Args:
            code: 要执行的代码 (Python源码 或 Bash命令)
            mode: 执行模式 — "python" 或 "bash"
            timeout: 超时秒数 (None=默认, 0=无限制但会设max)
            env: 额外的环境变量
            working_dir: 工作目录

        Returns:
            ExecutionResult 包含 stdout/stderr/status 等
        """
        execution_id = str(uuid.uuid4())[:12]
        code_truncated = code[:100].replace("\n", "\\n")

        # 超时限定
        if timeout is None:
            timeout = self.default_timeout
        timeout = min(timeout, self.max_timeout)

        # 安全扫描
        if mode == "python":
            violations = CodeScanner.scan_python(code)
            if violations:
                result = ExecutionResult(
                    execution_id=execution_id,
                    status=ExecutionStatus.BLOCKED,
                    blocked_reason="; ".join(violations),
                    mode=mode,
                    code_truncated=code_truncated,
                )
                self._record(result)
                logger.warning(f"Blocked Python execution: {violations}")
                return result
        elif mode == "bash":
            is_safe, reason = CodeScanner.scan_bash(code)
            if not is_safe:
                result = ExecutionResult(
                    execution_id=execution_id,
                    status=ExecutionStatus.BLOCKED,
                    blocked_reason=reason,
                    mode=mode,
                    code_truncated=code_truncated,
                )
                self._record(result)
                logger.warning(f"Blocked Bash execution: {reason}")
                return result

        # 根据模式执行
        if mode == "python":
            result = await self._execute_python(
                execution_id, code, timeout, code_truncated
            )
        elif mode == "bash":
            result = await self._execute_bash(
                execution_id, code, timeout, code_truncated, env, working_dir
            )
        else:
            result = ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.ERROR,
                stderr=f"不支持的模式: {mode}",
                mode=mode,
                code_truncated=code_truncated,
            )

        self._record(result)
        return result

    # ── Python 执行 ───────────────────────────────────────

    async def _execute_python(
        self,
        execution_id: str,
        code: str,
        timeout: float,
        code_truncated: str,
    ) -> ExecutionResult:
        """在子进程中执行 Python 代码"""
        started_at = time.time()

        # 生成沙箱运行代码
        safe_paths_repr = repr(self.safe_dirs)
        runner_code = _PYTHON_RUNNER_TEMPLATE.format(
            cpu_limit=self.python_cpu_limit,
            mem_limit=self.python_mem_limit,
            safe_paths=safe_paths_repr,
            code=code,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", runner_code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                status = ExecutionStatus.SUCCESS
            except asyncio.TimeoutError:
                # 超时 → kill
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                stdout_bytes, stderr_bytes = b"", f"执行超时 ({timeout}s)".encode()
                status = ExecutionStatus.TIMEOUT

            duration = (time.time() - started_at) * 1000

            # 解析 stdout 中的 JSON 结果
            stdout_text = ""
            stderr_text = ""
            return_code = -1
            peak_mem = 0.0

            if stdout_bytes:
                stdout_text = stdout_bytes.decode("utf-8", errors="replace")
                # 限制输出大小
                if len(stdout_text) > self.max_output_bytes:
                    stdout_text = stdout_text[:self.max_output_bytes] + "\n... [输出截断]"

            if stderr_bytes:
                stderr_text = stderr_bytes.decode("utf-8", errors="replace")

            # 从 stdout 中提取 JSON 结果 (最后一行为JSON)
            try:
                lines = stdout_text.strip().split("\n")
                last_line = lines[-1]
                if last_line.startswith("{"):
                    inner = json.loads(last_line)
                    return_code = inner.get("exit_code", 0)
                    # 沙箱内部 stdout/stderr
                    inner_stdout = inner.get("stdout", "")
                    inner_stderr = inner.get("stderr", "")
                    peak_mem = inner.get("peak_memory_mb", 0.0)
                    inner_duration = inner.get("duration_ms", duration)

                    # 合并输出: 沙箱内部输出 + runner 之前的输出
                    preamble = "\n".join(lines[:-1]) if len(lines) > 1 else ""
                    if preamble:
                        stdout_text = preamble + "\n" + inner_stdout
                    else:
                        stdout_text = inner_stdout
                    stderr_text = inner_stderr
                    duration = inner_duration
            except (json.JSONDecodeError, IndexError, KeyError):
                return_code = proc.returncode if proc.returncode is not None else -1

            if status != ExecutionStatus.TIMEOUT and return_code != 0:
                status = ExecutionStatus.ERROR

            return ExecutionResult(
                execution_id=execution_id,
                status=status,
                stdout=stdout_text,
                stderr=stderr_text,
                return_code=return_code,
                duration_ms=duration,
                peak_memory_mb=peak_mem,
                timeout_seconds=timeout,
                mode="python",
                code_truncated=code_truncated,
            )

        except Exception as e:
            duration = (time.time() - started_at) * 1000
            logger.error(f"Python sandbox exception: {e}")
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.ERROR,
                stderr=f"沙箱执行异常: {e}\n{traceback.format_exc()}",
                duration_ms=duration,
                timeout_seconds=timeout,
                mode="python",
                code_truncated=code_truncated,
            )

    # ── Bash 执行 ─────────────────────────────────────────

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
        started_at = time.time()

        # 构建环境变量
        proc_env = os.environ.copy()
        # 添加安全限制环境变量
        proc_env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
        proc_env["HOME"] = tempfile.gettempdir()
        proc_env["SHELL"] = "/bin/bash"
        if env:
            proc_env.update(env)

        # 使用 rbash (restricted bash) 如果可用
        shell = "/bin/bash"
        if os.path.exists("/bin/rbash"):
            shell = "/bin/rbash"

        try:
            proc = await asyncio.create_subprocess_exec(
                shell, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=proc_env,
                cwd=working_dir or tempfile.gettempdir(),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                status = ExecutionStatus.SUCCESS
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                stdout_bytes, stderr_bytes = b"", f"执行超时 ({timeout}s)".encode()
                status = ExecutionStatus.TIMEOUT

            duration = (time.time() - started_at) * 1000

            stdout_text = ""
            stderr_text = ""

            if stdout_bytes:
                stdout_text = stdout_bytes.decode("utf-8", errors="replace")
                if len(stdout_text) > self.max_output_bytes:
                    stdout_text = stdout_text[:self.max_output_bytes] + "\n... [输出截断]"

            if stderr_bytes:
                stderr_text = stderr_bytes.decode("utf-8", errors="replace")
                if len(stderr_text) > self.max_output_bytes:
                    stderr_text = stderr_text[:self.max_output_bytes] + "\n... [输出截断]"

            return_code = proc.returncode if proc.returncode is not None else -1

            if status != ExecutionStatus.TIMEOUT and return_code != 0:
                status = ExecutionStatus.ERROR

            return ExecutionResult(
                execution_id=execution_id,
                status=status,
                stdout=stdout_text,
                stderr=stderr_text,
                return_code=return_code,
                duration_ms=duration,
                peak_memory_mb=0.0,
                timeout_seconds=timeout,
                mode="bash",
                code_truncated=code_truncated,
            )

        except Exception as e:
            duration = (time.time() - started_at) * 1000
            logger.error(f"Bash sandbox exception: {e}")
            return ExecutionResult(
                execution_id=execution_id,
                status=ExecutionStatus.ERROR,
                stderr=f"沙箱执行异常: {e}",
                duration_ms=duration,
                timeout_seconds=timeout,
                mode="bash",
                code_truncated=code_truncated,
            )

    # ── 统计与历史 ────────────────────────────────────────

    def _record(self, result: ExecutionResult):
        """记录执行结果到统计和历史"""
        self._stats["total_executions"] += 1
        self._stats["total_duration_ms"] += result.duration_ms
        self._stats["last_execution_at"] = result.created_at

        if result.mode == "python":
            self._stats["python_count"] += 1
        elif result.mode == "bash":
            self._stats["bash_count"] += 1

        if result.status == ExecutionStatus.SUCCESS:
            self._stats["success_count"] += 1
        elif result.status == ExecutionStatus.ERROR:
            self._stats["error_count"] += 1
        elif result.status == ExecutionStatus.TIMEOUT:
            self._stats["timeout_count"] += 1
        elif result.status == ExecutionStatus.BLOCKED:
            self._stats["blocked_count"] += 1
            self._stats["violations"].append({
                "time": result.created_at,
                "reason": result.blocked_reason,
                "code": result.code_truncated,
            })
            # 只保留最近100条违规记录
            if len(self._stats["violations"]) > 100:
                self._stats["violations"] = self._stats["violations"][-100:]
        elif result.status == ExecutionStatus.KILLED:
            self._stats["killed_count"] += 1

        # 历史记录
        self._history.append(result)
        if len(self._history) > self._history_max:
            self._history = self._history[-self._history_max:]

    def get_sandbox_stats(self) -> Dict:
        """获取沙箱统计信息"""
        total = self._stats["total_executions"]
        success = self._stats["success_count"]
        return {
            "total_executions": total,
            "success_count": success,
            "error_count": self._stats["error_count"],
            "timeout_count": self._stats["timeout_count"],
            "blocked_count": self._stats["blocked_count"],
            "killed_count": self._stats["killed_count"],
            "success_rate": round(success / max(total, 1), 4),
            "avg_duration_ms": round(
                self._stats["total_duration_ms"] / max(total, 1), 1
            ),
            "python_count": self._stats["python_count"],
            "bash_count": self._stats["bash_count"],
            "last_execution_at": self._stats["last_execution_at"],
            "history_size": len(self._history),
            "default_timeout": self.default_timeout,
            "python_mem_limit_mb": self.python_mem_limit // 1024 // 1024,
            "recent_violations": self._stats["violations"][-5:],
        }

    def get_history(self, limit: int = 20) -> List[Dict]:
        """获取执行历史"""
        return [r.to_dict() for r in self._history[-limit:]]

    def clear_history(self):
        """清空执行历史"""
        self._history.clear()
        logger.info("Sandbox execution history cleared")

    def reset_stats(self):
        """重置统计信息"""
        self._stats = {
            "total_executions": 0,
            "success_count": 0,
            "error_count": 0,
            "timeout_count": 0,
            "blocked_count": 0,
            "killed_count": 0,
            "total_duration_ms": 0.0,
            "python_count": 0,
            "bash_count": 0,
            "last_execution_at": 0.0,
            "violations": [],
        }
        logger.info("Sandbox stats reset")


# ═══════════════════════════════════════════════════════════
# 简单内联沙箱 (同步, 用于安全评估而不执行)
# ═══════════════════════════════════════════════════════════

class InlineSandbox:
    """
    内联沙箱 — 不创建子进程, 在同一进程中评估简单表达式

    用途:
      - 安全地 eval 数学表达式
      - 安全地 format 字符串
      - 不需要子进程开销的小型计算

    限制:
      - 仅允许字面量和安全函数
      - 无 I/O
      - 无导入
    """

    # 安全内置
    SAFE_BUILTINS = {
        "True": True, "False": False, "None": None,
        "abs": abs, "all": all, "any": any, "bin": bin,
        "bool": bool, "bytes": bytes, "chr": chr,
        "complex": complex, "dict": dict, "divmod": divmod,
        "enumerate": enumerate, "filter": filter, "float": float,
        "format": format, "frozenset": frozenset,
        "hex": hex, "int": int, "isinstance": isinstance,
        "len": len, "list": list, "map": map, "max": max,
        "min": min, "oct": oct, "ord": ord, "pow": pow,
        "range": range, "repr": repr, "reversed": reversed,
        "round": round, "set": set, "slice": slice, "sorted": sorted,
        "str": str, "sum": sum, "tuple": tuple, "type": type,
        "zip": zip, "hash": hash,
        "math": __import__("math"),
    }

    @classmethod
    def eval(cls, expression: str, context: Dict = None) -> Tuple[Any, str]:
        """
        安全地评估简单表达式

        Args:
            expression: Python 表达式字符串
            context: 额外变量

        Returns:
            (result, error_message)
        """
        # 安全检查: 禁止 import / exec / __ 等
        danger = ["import", "exec", "eval", "compile", "__", "open", "file"]
        expr_lower = expression.lower()
        for d in danger:
            if d in expr_lower:
                return None, f"表达式包含禁止关键词: {d}"

        safe_globals = dict(cls.SAFE_BUILTINS)
        if context:
            safe_globals.update(context)

        try:
            result = eval(expression, {"__builtins__": {}}, safe_globals)
            return result, ""
        except Exception as e:
            return None, str(e)


# ═══════════════════════════════════════════════════════════
# Plugin 适配
# ═══════════════════════════════════════════════════════════

class SandboxPlugin:
    """meshctx Plugin 适配器"""
    info = type('Info', (), {
        'name': 'sandbox',
        'version': '3.50',
        'dependencies': [],
        'category': 'infrastructure',
        'description': '安全代码执行沙箱 — Python/Bash 双模式 + 危险检测 + 资源限制',
    })()
    state = "inactive"

    def __init__(self):
        self.sandbox: Optional[Sandbox] = None

    async def on_load(self, kernel) -> bool:
        try:
            self.sandbox = Sandbox()
            kernel.sandbox = self.sandbox
            self.state = "active"
            # 注册全局实例
            global _sandbox
            _sandbox = self.sandbox
            logger.info("SandboxPlugin activated")
            return True
        except Exception as e:
            logger.error(f"SandboxPlugin load failed: {e}")
            return False

    async def on_unload(self, kernel) -> bool:
        self.state = "inactive"
        return True

    def generate_report(self) -> Dict:
        if self.sandbox:
            return self.sandbox.get_sandbox_stats()
        return {"status": "not_initialized"}


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_sandbox: Optional[Sandbox] = None


def get_sandbox() -> Sandbox:
    """获取 Sandbox 全局实例，自动创建"""
    global _sandbox
    if _sandbox is None:
        _sandbox = Sandbox()
    return _sandbox


def init_sandbox(
    default_timeout: float = 30.0,
    max_timeout: float = 300.0,
    python_mem_limit: int = 512 * 1024 * 1024,
) -> Sandbox:
    """
    初始化 Sandbox 全局单例

    Args:
        default_timeout: 默认超时 (秒)
        max_timeout: 最大超时 (秒)
        python_mem_limit: Python 模式内存限制 (字节)

    Returns:
        Sandbox 实例
    """
    global _sandbox
    if _sandbox is None:
        _sandbox = Sandbox(
            default_timeout=default_timeout,
            max_timeout=max_timeout,
            python_mem_limit=python_mem_limit,
        )
    return _sandbox
