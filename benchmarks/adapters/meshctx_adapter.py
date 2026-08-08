"""
Meshctx Agent 适配器 — 通过 CLI 调用 meshctx agent 并解析输出

这是三个 benchmark harness 共用的适配器。通过 subprocess 调用
`meshctx task` 命令来运行 agent，并捕获其输出。

用法:
    adapter = MeshctxAdapter()
    result = adapter.run(task="修复 src/main.py 中的 bug")
    print(result.output)
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


class MeshctxAdapter:
    """通过 CLI 调用 meshctx agent 的适配器"""

    def __init__(
        self,
        project_path: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 600,
        max_steps: int = 30,
    ):
        """
        初始化适配器。

        参数:
            project_path: meshctx 项目路径，默认自动检测
            model: 使用的模型 ID，默认从环境变量读取
            timeout: agent 运行超时（秒）
            max_steps: agent 最大步数
        """
        self.project_path = project_path or self._detect_project_path()
        self.model = model or os.environ.get("MESHCTX_MODEL", "deepseek:v4-pro")
        self.timeout = timeout
        self.max_steps = max_steps

    @staticmethod
    def _detect_project_path() -> str:
        """自动检测 meshctx 项目路径"""
        candidates = [
            str(Path(__file__).resolve().parent.parent.parent),  # benchmarks 的上上级（meshctx-public）
            str(Path.home() / "meshctx-public"),
        ]
        for p in candidates:
            if (Path(p) / "src" / "cli.py").exists():
                return p
        return os.getcwd()

    def run(
        self,
        task: str,
        context: Optional[str] = None,
        env: Optional[dict] = None,
        timeout: Optional[int] = None,
        max_steps: Optional[int] = None,
    ) -> "AdapterResult":
        """
        运行 meshctx agent 执行任务。

        参数:
            task: 任务描述
            context: 附加上下文信息（如代码仓库路径）
            env: 额外的环境变量
            timeout: 覆盖默认超时
            max_steps: 覆盖默认步数

        返回:
            AdapterResult 包含输出、退出码、耗时等信息
        """
        timeout = timeout or self.timeout
        max_steps = max_steps or self.max_steps

        # 构建完整任务描述
        full_task = task
        if context:
            full_task = f"{task}\n\n上下文信息:\n{context}"

        # 构建命令 — 使用 `meshctx task` 命令（含 --json-output 结构化输出）
        cmd = [
            sys.executable, "-m", "src.cli", "task",
            "--max-steps", str(max_steps),
            "--json-output",
        ]
        if self.model:
            cmd.extend(["-m", self.model])
        cmd.append(full_task)

        # 准备环境变量
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        start_time = time.time()
        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_path,
                env=run_env,
                timeout=timeout,
            )

            elapsed = time.time() - start_time
            return AdapterResult(
                success=process.returncode == 0,
                output=process.stdout,
                error=process.stderr,
                exit_code=process.returncode,
                elapsed_seconds=round(elapsed, 2),
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            return AdapterResult(
                success=False,
                output="",
                error=f"Agent 运行超时 ({timeout}s)",
                exit_code=-1,
                elapsed_seconds=round(elapsed, 2),
                timed_out=True,
            )

    def run_with_retry(
        self,
        task: str,
        context: Optional[str] = None,
        max_retries: int = 2,
        **kwargs,
    ) -> "AdapterResult":
        """带重试的运行方法"""
        last_result: Optional[AdapterResult] = None
        for attempt in range(max_retries + 1):
            result = self.run(task=task, context=context, **kwargs)
            if result.success:
                return result
            last_result = result
            if attempt < max_retries:
                time.sleep(5 * (attempt + 1))  # 递增等待
        if last_result is not None:
            return last_result
        # 不应该到达这里（至少有一次尝试），但防御性返回
        return AdapterResult(
            success=False, output="", error="所有重试均已失败",
            exit_code=-1, elapsed_seconds=0, timed_out=False,
        )


class AdapterResult:
    """适配器运行结果"""

    def __init__(
        self,
        success: bool,
        output: str,
        error: str,
        exit_code: int,
        elapsed_seconds: float,
        timed_out: bool,
    ):
        self.success = success
        self.output = output
        self.error = error
        self.exit_code = exit_code
        self.elapsed_seconds = elapsed_seconds
        self.timed_out = timed_out

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "exit_code": self.exit_code,
            "elapsed_seconds": self.elapsed_seconds,
            "timed_out": self.timed_out,
        }

    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return f"AdapterResult({status} exit={self.exit_code} elapsed={self.elapsed_seconds}s)"
