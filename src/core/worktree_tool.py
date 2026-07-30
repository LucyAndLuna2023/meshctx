"""
meshctx Worktree — Git Worktree 隔离环境
对标: Claude Code EnterWorktree / ExitWorktree
"""
import os, subprocess, tempfile, shutil
from pathlib import Path
from typing import Optional
import logging
logger = logging.getLogger(__name__)

_worktrees: dict[str, dict] = {}  # id -> {path, base_branch, git_dir}

def worktree_create(branch: str = None, base_path: str = None,
                    from_branch: str = "main") -> dict:
    """创建隔离的 git worktree
    
    Args:
        branch: 新分支名 (自动生成如果不提供)
        base_path: worktree 路径 (自动选择如果不提供)
        from_branch: 基于哪个分支
    """
    import uuid
    if not branch:
        branch = f"meshctx-wt-{uuid.uuid4().hex[:8]}"
    
    cwd = os.getcwd()
    # 找到 git 根目录
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        return {"ok": False, "error": "Not in a git repository"}
    
    git_root = r.stdout.strip()
    
    if not base_path:
        base_path = os.path.join(tempfile.gettempdir(), f"meshctx-wt-{uuid.uuid4().hex[:8]}")
    
    # Fetch first
    subprocess.run(["git", "fetch", "origin"], capture_output=True, cwd=git_root, timeout=30)
    
    # Create worktree
    cmd = ["git", "worktree", "add", base_path]
    if branch:
        cmd += ["-b", branch]
    cmd.append(from_branch)
    
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=git_root, timeout=30)
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr, "branch": branch}
    
    wt_id = f"wt_{uuid.uuid4().hex[:8]}"
    _worktrees[wt_id] = {
        "id": wt_id, "path": base_path, "branch": branch,
        "git_root": git_root, "from_branch": from_branch
    }
    
    return {"ok": True, "worktree_id": wt_id, "path": base_path, "branch": branch,
            "from_branch": from_branch, "git_root": git_root}

def worktree_enter(worktree_id: str) -> dict:
    """进入 worktree（返回路径和分支信息）"""
    if worktree_id not in _worktrees:
        return {"ok": False, "error": f"Worktree {worktree_id} not found"}
    wt = _worktrees[worktree_id]
    path = wt["path"]
    if not os.path.isdir(path):
        return {"ok": False, "error": f"Worktree path {path} no longer exists"}
    return {"ok": True, "worktree_id": worktree_id, "path": path, 
            "branch": wt["branch"], "note": f"cd {path}  # to enter this worktree"}

def worktree_list() -> dict:
    """列出所有 worktrees（包括 git worktree list）"""
    result = {"active": list(_worktrees.values())}
    try:
        r = subprocess.run(["git", "worktree", "list"], capture_output=True, text=True)
        result["git_worktrees"] = r.stdout.strip()
    except Exception as _e:
        logger.exception("Unexpected error: %s", _e)
    return result

def worktree_remove(worktree_id: str, force: bool = False) -> dict:
    """删除 worktree"""
    if worktree_id not in _worktrees:
        return {"ok": False, "error": f"Worktree {worktree_id} not found"}
    wt = _worktrees[worktree_id]
    path = wt["path"]
    branch = wt["branch"]
    git_root = wt["git_root"]
    
    if os.path.isdir(path):
        # git worktree remove
        cmd = ["git", "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(path)
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=git_root, timeout=15)
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr}
    
    # Delete branch if it was ours
    subprocess.run(["git", "branch", "-D", branch], capture_output=True, cwd=git_root)
    
    del _worktrees[worktree_id]
    return {"ok": True, "removed": path, "branch": branch}

def worktree_cleanup() -> dict:
    """清理所有 meshctx 创建的 worktrees"""
    removed = []
    for wt_id in list(_worktrees.keys()):
        r = worktree_remove(wt_id, force=True)
        if r.get("ok"):
            removed.append(r.get("branch"))
    return {"ok": True, "cleaned": removed}
