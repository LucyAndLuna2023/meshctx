"""
MeshCtx Sandbox — Secure Code Execution Engine
================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Isolated code execution with Docker container + subprocess fallback.
Supports Python, Bash, JavaScript with resource limits and file sandboxing.

License: AGPLv3 for non-commercial use only.
         Commercial use REQUIRES a separate license.
         Contact: license@meshctx.com
"""
import asyncio
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────
DEFAULT_TIMEOUT = 30  # seconds
MAX_TIMEOUT = 120
MAX_OUTPUT_BYTES = 256 * 1024  # 256KB
MAX_MEMORY_MB = 256
DOCKER_IMAGE = "python:3.12-slim"
SANDBOX_WORKDIR = "/sandbox"


class SandboxResult:
    """Result from sandbox execution."""
    def __init__(self, success: bool, stdout: str = "", stderr: str = "",
                 exit_code: int = -1, duration_ms: float = 0,
                 truncated: bool = False, method: str = "unknown"):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.duration_ms = duration_ms
        self.truncated = truncated
        self.method = method  # "docker" or "subprocess"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": round(self.duration_ms, 1),
            "truncated": self.truncated,
            "method": self.method,
        }


class SandboxEngine:
    """Secure code execution sandbox with Docker + subprocess fallback."""

    SUPPORTED_LANGUAGES = {
        "python": {"ext": ".py", "cmd": ["python3", "{file}"], "image": "python:3.12-slim"},
        "bash": {"ext": ".sh", "cmd": ["bash", "{file}"], "image": "bash:5.2"},
        "javascript": {"ext": ".js", "cmd": ["node", "{file}"], "image": "node:20-slim"},
    }

    def __init__(self, work_dir: Optional[str] = None):
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="meshctx_sandbox_")
        self._docker_available: Optional[bool] = None
        os.makedirs(self.work_dir, exist_ok=True)

    def _check_docker(self) -> bool:
        """Check if Docker is available."""
        if self._docker_available is None:
            try:
                result = subprocess.run(
                    ["docker", "info", "--format", "{{.ServerVersion}}"],
                    capture_output=True, timeout=5
                )
                self._docker_available = result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._docker_available = False
            logger.info(f"Docker available: {self._docker_available}")
        return self._docker_available

    async def execute(self, code: str, language: str = "python",
                      timeout: int = DEFAULT_TIMEOUT,
                      env: Optional[Dict[str, str]] = None) -> SandboxResult:
        """
        Execute code in a sandboxed environment.

        Args:
            code: Source code to execute
            language: "python", "bash", or "javascript"
            timeout: Max execution time in seconds (1-120)
            env: Environment variables to inject

        Returns:
            SandboxResult with stdout, stderr, exit_code
        """
        if language not in self.SUPPORTED_LANGUAGES:
            return SandboxResult(False, stderr=f"Unsupported language: {language}",
                                 method="error")

        timeout = min(max(timeout, 1), MAX_TIMEOUT)
        t_start = time.time()

        try:
            if self._check_docker():
                result = await self._execute_docker(code, language, timeout, env)
            else:
                logger.warning("Docker not available, using subprocess fallback")
                result = await self._execute_subprocess(code, language, timeout, env)
        except Exception as e:
            logger.exception(f"Sandbox execution failed: {e}")
            result = SandboxResult(False, stderr=str(e), method="error")

        result.duration_ms = (time.time() - t_start) * 1000
        return result

    async def _execute_docker(self, code: str, language: str,
                               timeout: int, env: Optional[Dict[str, str]]) -> SandboxResult:
        """Execute code inside a Docker container."""
        lang_info = self.SUPPORTED_LANGUAGES[language]
        code_hash = hashlib.md5(code.encode()).hexdigest()[:8]

        # Write code to temp file
        tmp_dir = tempfile.mkdtemp(prefix=f"sandbox_{code_hash}_")
        code_file = os.path.join(tmp_dir, f"code{lang_info['ext']}")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)

        # Build docker command
        docker_cmd = [
            "docker", "run", "--rm",
            "--network", "none",  # No network access
            "--memory", f"{MAX_MEMORY_MB}m",
            "--cpus", "1",
            "--read-only",  # Read-only root filesystem
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
            "--tmpfs", f"{SANDBOX_WORKDIR}:rw,noexec,nosuid,size=64m",
            "--workdir", SANDBOX_WORKDIR,
            "-v", f"{tmp_dir}:/input:ro",  # Mount code as read-only
        ]

        # Add environment variables
        if env:
            for k, v in env.items():
                docker_cmd.extend(["-e", f"{k}={v}"])

        docker_cmd.append(lang_info["image"])

        # Build the execution command inside container
        cmd_in_container = []
        if language == "python":
            cmd_in_container = ["python3", "-u", f"/input/code{lang_info['ext']}"]
        elif language == "bash":
            cmd_in_container = ["bash", f"/input/code{lang_info['ext']}"]
        elif language == "javascript":
            cmd_in_container = ["node", f"/input/code{lang_info['ext']}"]

        docker_cmd.extend(cmd_in_container)

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return SandboxResult(
                    False,
                    stdout="",
                    stderr=f"Execution timed out after {timeout}s",
                    exit_code=-1,
                    method="docker"
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            truncated = False
            if len(stdout) > MAX_OUTPUT_BYTES:
                stdout = stdout[:MAX_OUTPUT_BYTES] + "\n... [output truncated at 256KB]"
                truncated = True

            return SandboxResult(
                success=proc.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode or 0,
                truncated=truncated,
                method="docker"
            )

        finally:
            # Cleanup temp files
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    async def _execute_subprocess(self, code: str, language: str,
                                   timeout: int, env: Optional[Dict[str, str]]) -> SandboxResult:
        """Execute code via subprocess with resource limits (fallback)."""
        lang_info = self.SUPPORTED_LANGUAGES[language]
        code_hash = hashlib.md5(code.encode()).hexdigest()[:8]

        # Write code to sandbox directory
        sub_dir = os.path.join(self.work_dir, code_hash)
        os.makedirs(sub_dir, exist_ok=True)
        code_file = os.path.join(sub_dir, f"code{lang_info['ext']}")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)

        # Build command
        cmd = [arg.replace("{file}", code_file) for arg in lang_info["cmd"]]

        # Environment
        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=proc_env,
                cwd=sub_dir,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return SandboxResult(
                    False,
                    stdout="",
                    stderr=f"Execution timed out after {timeout}s",
                    exit_code=-1,
                    method="subprocess"
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            truncated = False
            if len(stdout) > MAX_OUTPUT_BYTES:
                stdout = stdout[:MAX_OUTPUT_BYTES] + "\n... [output truncated at 256KB]"
                truncated = True

            return SandboxResult(
                success=proc.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode or 0,
                truncated=truncated,
                method="subprocess"
            )

        finally:
            # Cleanup
            try:
                shutil.rmtree(sub_dir, ignore_errors=True)
            except Exception:
                pass

    def cleanup(self):
        """Clean up sandbox working directory."""
        shutil.rmtree(self.work_dir, ignore_errors=True)


# Global instance (lazy init)
_sandbox: Optional[SandboxEngine] = None


def get_sandbox() -> SandboxEngine:
    global _sandbox
    if _sandbox is None:
        _sandbox = SandboxEngine()
    return _sandbox
