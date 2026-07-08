"""meshctx git_ops — Git workflow integration (pr_review, worktree, branch context)"""
# v3.115.14: initial git workflow stubs

import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime


# ── helpers ─────────────────────────────────────────────────────────────────

def _run_git(*args: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Run a git command and return the CompletedProcess."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        timeout=30,
    )


def _git_output(*args: str, cwd: Optional[Path] = None) -> str:
    """Run git and return stripped stdout, or raise on failure."""
    proc = _run_git(*args, cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def _repo_root() -> Path:
    """Return the absolute path to the current git repository root."""
    return Path(_git_output("rev-parse", "--show-toplevel"))


# ── public API ──────────────────────────────────────────────────────────────


def create_fix_branch(issue_id: str, base: str = "main") -> Dict[str, Any]:
    """Create and checkout a fix branch.

    Returns:
        dict: {"branch_name": str} on success, {"error": str} on failure.
    """
    try:
        branch = f"fix/{issue_id}"
        _git_output("checkout", base)
        _git_output("checkout", "-b", branch)
        return {"branch_name": branch}
    except Exception as e:
        return {"error": str(e)}


def pr_review(base_branch: str = "main") -> Dict[str, Any]:
    """Generate a PR-ready diff against a base branch.

    Returns:
        dict: {"diff_text": str, "files_changed": int, "stats": str}
               or {"error": str} on failure.
    """
    try:
        diff_text = _git_output("diff", f"{base_branch}...HEAD")
        files_changed = len(_git_output(
            "diff", "--name-only", f"{base_branch}...HEAD"
        ).splitlines()) if diff_text else 0
        stats = _git_output("diff", "--stat", f"{base_branch}...HEAD")
        return {
            "diff_text": diff_text,
            "files_changed": files_changed,
            "stats": stats,
        }
    except Exception as e:
        return {"error": str(e)}


def branch_aware_context() -> Dict[str, Any]:
    """Return context about the current branch and working tree state.

    Returns:
        dict: {
            "branch": str,
            "changed_files": [...],
            "staged": [...],
            "unstaged": [...],
            "recent_commits": [{"sha": str, "msg": str, "date": str}, ...],
        } or {"error": str} on failure.
    """
    try:
        branch = _git_output("rev-parse", "--abbrev-ref", "HEAD")

        # changed files (unstaged modifications)
        unstaged_raw = _git_output(
            "diff", "--name-only", "HEAD"
        ).splitlines()
        unstaged = [f for f in unstaged_raw if f]

        # staged files
        staged_raw = _git_output(
            "diff", "--name-only", "--cached"
        ).splitlines()
        staged = [f for f in staged_raw if f]

        # all changed + untracked files (porcelain)
        changed_files: List[str] = []
        try:
            status_out = _git_output("status", "--porcelain")
            for line in status_out.splitlines():
                if line.strip():
                    # strip status flags, leave filename
                    fname = line[3:].strip()
                    if fname:
                        changed_files.append(fname)
        except Exception:
            changed_files = list(set(unstaged + staged))

        # recent commits (last 5)
        recent_commits: List[Dict[str, str]] = []
        try:
            log_out = _git_output(
                "log", "-5", "--format=%H%x00%s%x00%ai"
            )
            for line in log_out.splitlines():
                if not line.strip():
                    continue
                parts = line.split("\x00")
                if len(parts) >= 3:
                    recent_commits.append({
                        "sha": parts[0][:8],
                        "msg": parts[1],
                        "date": parts[2],
                    })
        except Exception:
            pass

        return {
            "branch": branch,
            "changed_files": changed_files,
            "staged": staged,
            "unstaged": unstaged,
            "recent_commits": recent_commits,
        }
    except Exception as e:
        return {"error": str(e)}


def worktree_fix(
    issue_id: str,
    description: str,
    base_branch: str = "main",
) -> Dict[str, Any]:
    """Create a git worktree for isolated work on a fix.

    Returns:
        dict: {"worktree_path": str, "branch_name": str}
               or {"error": str} on failure.
    """
    try:
        root = _repo_root()
        worktree_path = root.parent / f"fix-{issue_id}"
        branch_name = f"fix/{issue_id}"

        # Remove existing worktree if present
        try:
            _git_output("worktree", "remove", str(worktree_path), "--force")
        except Exception:
            pass

        # Remove directory if it still exists
        if worktree_path.exists():
            import shutil
            shutil.rmtree(str(worktree_path), ignore_errors=True)

        _git_output(
            "worktree", "add",
            str(worktree_path),
            "-b", branch_name,
            base_branch,
        )

        return {
            "worktree_path": str(worktree_path),
            "branch_name": branch_name,
        }
    except Exception as e:
        return {"error": str(e)}


def commit_fix(
    issue_id: str,
    message: str,
    files: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Stage, commit, and push changes for a fix.

    Args:
        files: Optional list of file paths to stage. If None, stages all changes.

    Returns:
        dict: {"success": bool, "commit_sha": str} or {"error": str} on failure.
    """
    try:
        if files:
            for f in files:
                _git_output("add", f)
        else:
            _git_output("add", "-A")

        _git_output("commit", "-m", f"fix({issue_id}): {message}")
        sha = _git_output("rev-parse", "HEAD")

        return {
            "success": True,
            "commit_sha": sha,
        }
    except Exception as e:
        # git commit may fail if nothing to commit; still try push
        if "nothing to commit" in str(e):
            return {"success": False, "commit_sha": "", "error": str(e)}
        return {"error": str(e)}


def get_status() -> Dict[str, Any]:
    """Return git status in porcelain format.

    Returns:
        dict: {"status": str} or {"error": str} on failure.
    """
    try:
        status = _git_output("status", "--porcelain")
        return {"status": status}
    except Exception as e:
        return {"error": str(e)}


def list_fix_branches() -> Dict[str, Any]:
    """List all fix/* branches.

    Returns:
        dict: {"branches": [...]} or {"error": str} on failure.
    """
    try:
        out = _git_output("branch", "--list", "fix/*")
        branches = [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]
        return {"branches": branches}
    except Exception as e:
        return {"error": str(e)}


# ── _P stub class (backward compat) ─────────────────────────────────────────

from ._stub import _P

# ── module-level __getattr__ fallback ───────────────────────────────────────

def __getattr__(name):
    return _P(name)
