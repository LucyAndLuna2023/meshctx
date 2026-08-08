"""
Terminal-Bench 2.0 Meshctx 适配器

Terminal-Bench 专用的适配器扩展，继承自通用 MeshctxAdapter，
添加了终端命令执行和输出捕获功能。
"""

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

# 导入通用适配器
_adapter_dir = str(Path(__file__).resolve().parent.parent.parent / "adapters")
if _adapter_dir not in sys.path:
    sys.path.insert(0, _adapter_dir)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from adapters.meshctx_adapter import MeshctxAdapter, AdapterResult  # noqa: E402


class TerminalBenchAdapter(MeshctxAdapter):
    """
    Terminal-Bench 2.0 专用适配器

    扩展功能:
    - 终端命令执行和输出捕获
    - 多命令链式执行
    - 输出解析和结构化
    """

    def __init__(self, work_dir: Optional[str] = None, **kwargs):
        """
        初始化 Terminal-Bench 适配器。

        参数:
            work_dir: 工作目录
            **kwargs: 传递给 MeshctxAdapter 的参数
        """
        super().__init__(**kwargs)
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="termbench_"))
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def execute_commands(
        self,
        commands: List[str],
        timeout: int = 120,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict:
        """
        执行一系列 shell 命令。

        参数:
            commands: 命令列表
            timeout: 总超时秒数
            env: 环境变量

        返回:
            执行结果字典
        """
        results = []
        overall_success = True
        combined_stdout = ""
        combined_stderr = ""

        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        for cmd in commands:
            cmd_start = time.time()
            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=str(self.work_dir),
                    env=run_env,
                    timeout=timeout,
                )
                elapsed = time.time() - cmd_start

                results.append({
                    "command": cmd,
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "elapsed": round(elapsed, 3),
                    "success": proc.returncode == 0,
                })

                combined_stdout += proc.stdout
                combined_stderr += proc.stderr

                if proc.returncode != 0:
                    overall_success = False
                    break

            except subprocess.TimeoutExpired:
                elapsed = time.time() - cmd_start
                results.append({
                    "command": cmd,
                    "exit_code": -1,
                    "stdout": "[超时]",
                    "stderr": f"命令执行超时 ({timeout}s)",
                    "elapsed": round(elapsed, 3),
                    "success": False,
                })
                overall_success = False
                break

            except Exception as e:
                results.append({
                    "command": cmd,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": str(e),
                    "elapsed": 0,
                    "success": False,
                })
                overall_success = False
                break

        return {
            "success": overall_success,
            "commands": results,
            "combined_stdout": combined_stdout,
            "combined_stderr": combined_stderr,
            "total_commands": len(commands),
            "successful_commands": sum(1 for r in results if r["success"]),
        }

    def execute_single(self, command: str, **kwargs) -> Dict:
        """执行单条命令的便捷方法"""
        return self.execute_commands([command], **kwargs)

    def run_task(self, task: Dict) -> Dict:
        """
        完整运行一个 Terminal-Bench 任务:

        1. 执行 setup 命令
        2. 运行 meshctx agent 获取解决方案
        3. 从 agent 输出提取命令并执行
        4. 验证输出

        参数:
            task: 任务字典

        返回:
            包含所有步骤结果的字典
        """
        task_id = task.get("task_id", "unknown")
        setup_commands = task.get("setup_commands", [])
        expected_output = task.get("expected_output", "")
        prompt = task.get("prompt", task.get("description", ""))

        result = {
            "task_id": task_id,
            "stages": {},
        }

        # Stage 1: Setup
        if setup_commands:
            setup_result = self.execute_commands(setup_commands, timeout=60)
            result["stages"]["setup"] = {
                "success": setup_result["success"],
                "commands_run": setup_result["total_commands"],
            }
            if not setup_result["success"]:
                result["stages"]["setup"]["error"] = "Setup 命令执行失败"
        else:
            result["stages"]["setup"] = {"success": True, "commands_run": 0}

        # Stage 2: Agent 执行
        task_desc = f"在终端中执行以下任务，直接运行 shell 命令:\n\n{prompt}"
        agent_result = self.run_with_retry(
            task=task_desc,
            context=f"工作目录: {self.work_dir}\n任务ID: {task_id}",
        )
        result["stages"]["agent"] = agent_result.to_dict()

        # Stage 3: 从 agent 输出提取命令并执行
        extracted_commands = self._extract_commands(agent_result.output)
        if extracted_commands:
            exec_result = self.execute_commands(extracted_commands, timeout=120)
            result["stages"]["execution"] = {
                "success": exec_result["success"],
                "commands": exec_result["commands"],
                "combined_stdout": exec_result["combined_stdout"],
            }
        else:
            # 无法提取命令时，直接用 agent 输出作为结果
            result["stages"]["execution"] = {
                "success": agent_result.success,
                "commands": [],
                "combined_stdout": agent_result.output,
            }

        # Stage 4: 验证输出
        actual_output = result["stages"]["execution"].get("combined_stdout", "")
        output_match = self._match_output(actual_output, expected_output)
        result["stages"]["verification"] = {
            "output_match": output_match,
            "expected": expected_output,
            "actual_preview": actual_output[:200],
        }

        # 综合判断
        result["passed"] = (
            result["stages"].get("execution", {}).get("success", False)
            and output_match
        )

        return result

    @staticmethod
    def _extract_commands(text: str) -> List[str]:
        """从 agent 输出中提取 shell 命令"""
        if not text:
            return []

        commands = []

        # 匹配 ```bash ... ``` 或 ```sh ... ``` 代码块
        for match in re.finditer(r"```(?:ba)?sh\s*\n(.*?)```", text, re.DOTALL):
            for line in match.group(1).strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    # 去掉行首的 $ 或 >
                    line = re.sub(r"^[\$>]\s*", "", line)
                    commands.append(line)

        # 匹配以 $ 开头的单行命令
        if not commands:
            for match in re.finditer(r"^\$\s+(.+)$", text, re.MULTILINE):
                commands.append(match.group(1).strip())

        return commands if commands else []

    @staticmethod
    def _match_output(actual: str, expected: str) -> bool:
        """检查实际输出是否匹配期望输出"""
        if not expected:
            return True
        if not actual:
            return False

        actual_norm = " ".join(actual.lower().split())
        expected_norm = " ".join(expected.lower().split())

        return expected_norm in actual_norm
