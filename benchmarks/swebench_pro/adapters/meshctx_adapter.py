"""
SWE-bench Pro Meshctx 适配器

SWE-bench Pro 专用的适配器扩展，继承自通用 MeshctxAdapter，
添加了仓库管理和 patch 验证功能。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional

# 导入通用适配器模块
_adapter_dir = str(Path(__file__).resolve().parent.parent.parent / "adapters")
if _adapter_dir not in sys.path:
    sys.path.insert(0, _adapter_dir)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from adapters.meshctx_adapter import MeshctxAdapter, AdapterResult  # noqa: E402


class SWEBenchAdapter(MeshctxAdapter):
    """
    SWE-bench Pro 专用适配器

    扩展功能:
    - 仓库 clone 和管理
    - Patch 应用和验证
    - 测试运行
    """

    def __init__(self, workspace_dir: Optional[str] = None, **kwargs):
        """
        初始化 SWE-bench 适配器。

        参数:
            workspace_dir: 工作空间目录（用于 clone 仓库）
            **kwargs: 传递给 MeshctxAdapter 的参数
        """
        super().__init__(**kwargs)
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path(tempfile.mkdtemp(prefix="swebench_"))
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def clone_repo(self, repo_url: str, commit: str = "") -> Path:
        """
        Clone 仓库到工作空间。

        参数:
            repo_url: 仓库 URL
            commit: 要 checkout 的 commit

        返回:
            仓库本地路径
        """
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        repo_path = self.workspace_dir / repo_name

        if repo_path.exists():
            return repo_path

        # Clone
        cmd = ["git", "clone", repo_url, str(repo_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"Clone 失败: {result.stderr}")

        # Checkout commit
        if commit:
            subprocess.run(
                ["git", "checkout", commit],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=30,
            )

        return repo_path

    def apply_patch(self, repo_path: Path, patch_content: str) -> Dict:
        """
        应用 patch 到仓库。

        参数:
            repo_path: 仓库路径
            patch_content: patch 文本内容

        返回:
            应用结果字典
        """
        patch_file = repo_path / "_temp.patch"
        patch_file.write_text(patch_content, encoding="utf-8")

        try:
            result = subprocess.run(
                ["git", "apply", "--check", str(patch_file)],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                apply_result = subprocess.run(
                    ["git", "apply", str(patch_file)],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return {
                    "success": apply_result.returncode == 0,
                    "error": apply_result.stderr,
                    "stage": "applied",
                }
            else:
                return {
                    "success": False,
                    "error": result.stderr.strip(),
                    "stage": "check_failed",
                }
        finally:
            if patch_file.exists():
                patch_file.unlink()

    def run_tests(self, repo_path: Path, test_cmd: str = "pytest") -> Dict:
        """
        在仓库中运行测试。

        参数:
            repo_path: 仓库路径
            test_cmd: 测试命令

        返回:
            测试运行结果
        """
        try:
            result = subprocess.run(
                test_cmd.split(),
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "success": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": "测试运行超时",
            }

    def run_instance(self, task: Dict) -> Dict:
        """
        完整运行一个 SWE-bench instance:
        1. Clone 仓库 → 2. Agent 修复 → 3. Apply patch → 4. Run tests

        参数:
            task: 任务字典

        返回:
            包含所有步骤结果的字典
        """
        instance_id = task.get("instance_id", "unknown")
        repo_url = task.get("repo", "")
        base_commit = task.get("base_commit", "")
        problem = task.get("problem_statement", "")

        result = {
            "instance_id": instance_id,
            "stages": {},
        }

        # Stage 1: Clone
        try:
            repo_path = self.clone_repo(repo_url, base_commit)
            result["stages"]["clone"] = {"success": True, "path": str(repo_path)}
        except Exception as e:
            result["stages"]["clone"] = {"success": False, "error": str(e)}
            return result

        # Stage 2: Agent 修复
        task_desc = f"请修复以下问题:\n\n{problem}\n\n请以 unified diff 格式输出补丁（```diff ... ```）。"
        agent_result = self.run_with_retry(
            task=task_desc,
            context=f"仓库路径: {repo_path}\n实例ID: {instance_id}",
        )
        result["stages"]["agent"] = agent_result.to_dict()

        # Stage 3: Apply patch
        if agent_result.success:
            patch: str = ""
            # 从输出中提取 patch
            for pat in [r"```diff\s*\n(.*?)```", r"```patch\s*\n(.*?)```", r"(diff --git.*?)(?:\n\Z|\n(?=```|$))"]:
                match = re.search(pat, agent_result.output, re.DOTALL)
                if match:
                    patch = match.group(1).strip()
                    break
            if not patch:
                patch = agent_result.output.strip()

            apply_result = self.apply_patch(repo_path, patch)
            result["stages"]["apply"] = apply_result

            # Stage 4: Test
            test_cmd = task.get("test_cmd", "pytest")
            test_result = self.run_tests(repo_path, test_cmd)
            result["stages"]["test"] = test_result
        else:
            result["stages"]["apply"] = {"success": False, "error": "Agent 未成功生成 patch"}
            result["stages"]["test"] = {"success": False, "error": "由于 agent 失败，跳过测试"}

        return result
