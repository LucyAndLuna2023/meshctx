"""
Workflow Orchestration Engine
==============================

Dynamic multi-step workflow orchestration with subagent task execution,
dependency-graph-based parallel scheduling, retry logic with exponential
backoff, timeout enforcement, and result aggregation.

Usage::

    from src.core.workflow import workflow_define, workflow_run, workflow_status

    workflow_define("deploy", [
        {"id": "lint",   "command": "ruff check .", "timeout": 30},
        {"id": "test",   "command": "pytest", "depends_on": ["lint"], "timeout": 120},
        {"id": "build",  "command": "python -m build", "depends_on": ["test"], "timeout": 60},
        {"id": "deploy", "command": "scp dist/* server:", "depends_on": ["build"], "retry": 2},
    ])

    run_id = workflow_run("deploy", context={"branch": "main"})
    status = workflow_status(run_id)
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# ── Logging ──────────────────────────────────────────────────────────────
logger = logging.getLogger("meshctx.workflow")

# ── Exceptions ───────────────────────────────────────────────────────────
class WorkflowError(Exception):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Base exception for workflow engine errors."""

class WorkflowNotFoundError(WorkflowError):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Raised when a named workflow definition is not found."""

class WorkflowValidationError(WorkflowError):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Raised when a workflow definition is structurally invalid."""

class StepExecutionError(WorkflowError):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Raised when a step fails after exhausting retries."""

class StepTimeoutError(WorkflowError):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Raised when a step exceeds its timeout."""


# ── Status Enum ──────────────────────────────────────────────────────────
class StepStatus(Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Possible states of a workflow step during execution."""
    PENDING   = "pending"     # Not yet ready (dependencies unsatisfied)
    READY     = "ready"       # Dependencies satisfied, queued for execution
    RUNNING   = "running"     # Currently executing
    SUCCESS   = "success"     # Completed successfully
    FAILED    = "failed"      # Completed with error (retries exhausted)
    RETRYING  = "retrying"    # Temporarily failed, will retry
    SKIPPED   = "skipped"     # Skipped because a dependency failed
    TIMEOUT   = "timeout"     # Timed out


class RunStatus(Enum):
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """Overall status of a workflow run."""
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    CANCELLED = "cancelled"
    TIMEOUT   = "timeout"


# ── Data Classes ─────────────────────────────────────────────────────────
@dataclass
class WorkflowStep:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """A single step within a workflow.

    Attributes:
        id: Unique identifier within this workflow (e.g. ``"lint"``).
        command: Shell command string to execute, or a dot-separated tool path
                 (e.g. ``"pytest"``, ``"subagent.run_analysis"``).
        tool: Alternative structured tool specification as a dict with
              ``{"name": str, "args": dict}``.  Mutually exclusive with
              ``command`` — one must be provided.
        depends_on: List of step ``id`` values that must complete successfully
                    before this step can begin.
        timeout: Maximum wall-clock seconds for this step.  *Default: 300*.
        retry: Number of retry attempts on failure. *Default: 0*.
        retry_delay: Base delay in seconds for exponential backoff. *Default: 2*.
        cwd: Working directory for command execution. *Default: current dir*.
        env: Extra environment variables to inject.
    """
    id: str
    command: Optional[str] = None
    tool: Optional[Dict[str, Any]] = None
    depends_on: List[str] = field(default_factory=list)
    timeout: float = 300.0
    retry: int = 0
    retry_delay: float = 2.0
    cwd: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self, **kw) -> None:
        if not self.id or not isinstance(self.id, str):
            raise WorkflowValidationError(f"Step id must be a non-empty string, got {self.id!r}")
        if not self.command and not self.tool:
            raise WorkflowValidationError(
                f"Step {self.id!r}: either 'command' or 'tool' must be provided"
            )
        if self.command and self.tool:
            raise WorkflowValidationError(
                f"Step {self.id!r}: 'command' and 'tool' are mutually exclusive"
            )
        if self.timeout <= 0:
            raise WorkflowValidationError(f"Step {self.id!r}: timeout must be > 0")
        if self.retry < 0:
            raise WorkflowValidationError(f"Step {self.id!r}: retry must be >= 0")


@dataclass
class WorkflowDefinition:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """A named, validated workflow template.

    Created via :func:`workflow_define`.
    """
    name: str
    steps: Dict[str, WorkflowStep]
    step_order: List[str]  # topological order

    @property
    def step_ids(self, **kw) -> List[str]:
        """Return step ids in the order they were defined."""
        return list(self.steps.keys())


@dataclass
class StepResult:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """The outcome of a single step execution, including retry history."""
    step_id: str
    status: StepStatus = StepStatus.PENDING
    output: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    attempt: int = 0
    attempts: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def elapsed(self, **kw) -> float:
        """Wall-clock duration in seconds, or 0 if not started."""
        if self.started_at == 0:
            return 0.0
        end = self.finished_at or time.monotonic()
        return max(0.0, end - self.started_at)


@dataclass
class WorkflowRun:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """A single execution instance of a workflow definition."""
    id: str
    name: str
    context: Dict[str, Any]
    status: RunStatus = RunStatus.PENDING
    step_results: Dict[str, StepResult] = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def elapsed(self, **kw) -> float:
        """Total wall-clock duration in seconds."""
        if self.started_at == 0:
            return 0.0
        end = self.finished_at or time.monotonic()
        return max(0.0, end - self.started_at)

    def to_dict(self, **kw) -> Dict[str, Any]:
        """Serialize the run to a plain dict for status reporting."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "context": self.context,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed": self.elapsed,
            "steps": {
                sid: {
                    "status": sr.status.value,
                    "output": sr.output[:500] if sr.output else "",
                    "error": sr.error[:500] if sr.error else "",
                    "elapsed": sr.elapsed,
                    "attempt": sr.attempt,
                }
                for sid, sr in self.step_results.items()
            },
        }


# ── Registries (thread-safe in-memory stores) ───────────────────────────
_registry_lock = threading.RLock()

_workflows: Dict[str, WorkflowDefinition] = {}   # name → definition
_runs: Dict[str, WorkflowRun] = {}                # run_id → run


# ── Executor callback (pluggable by host system) ─────────────────────────
# By default we use subprocess; the host agent can swap this with a real
# subagent dispatcher, e.g. an async function that routes to LLM calls.
_step_executor: Optional[Callable[..., Any]] = None


def set_step_executor(fn: Callable[..., Any]) -> None:
    """Replace the default step executor.

    *fn* must be an async callable with signature::

        async def executor(step: WorkflowStep, context: dict) -> (str, str):
            # runs the step (command or tool), returns (stdout, stderr)
    """
    global _step_executor
    _step_executor = fn


# ── Default Executor (subprocess) ────────────────────────────────────────
async def _default_executor(step: WorkflowStep, context: Dict[str, Any]) -> Tuple[str, str]:
    """Execute a shell command via subprocess.

    Returns:
        ``(stdout, stderr)`` tuple.
    """
    import os
    import subprocess as sp

    env = os.environ.copy()
    env.update(step.env)
    # Inject context as environment variables prefixed with WF_
    for key, val in context.items():
        if isinstance(val, (str, int, float, bool)):
            env[f"WF_{key.upper()}"] = str(val)

    try:
        proc = await asyncio.create_subprocess_shell(
            step.command or "",
            stdout=sp.PIPE,
            stderr=sp.PIPE,
            cwd=step.cwd,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=step.timeout
        )
        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            raise StepExecutionError(
                f"Step {step.id!r} exited with code {proc.returncode}: {err or out}"
            )
        return out, err
    except asyncio.TimeoutError:
        raise StepTimeoutError(f"Step {step.id!r} timed out after {step.timeout}s")


# ── Topological Sort ─────────────────────────────────────────────────────
def _topological_sort(steps: Dict[str, WorkflowStep]) -> List[str]:
    """Return step ids in dependency-respecting order.

    Raises :class:`WorkflowValidationError` on cycles or missing dependencies.
    """
    in_degree: Dict[str, int] = {sid: 0 for sid in steps}
    children: Dict[str, List[str]] = {sid: [] for sid in steps}

    for sid, step in steps.items():
        for dep in step.depends_on:
            if dep not in steps:
                raise WorkflowValidationError(
                    f"Step {sid!r} depends on unknown step {dep!r}"
                )
            in_degree[sid] += 1
            children[dep].append(sid)

    # Start with nodes that have no dependencies
    queue: List[str] = [sid for sid, deg in in_degree.items() if deg == 0]
    result: List[str] = []

    while queue:
        # Sort for deterministic order
        queue.sort()
        node = queue.pop(0)
        result.append(node)
        for child in children.get(node, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(result) != len(steps):
        cycle = _detect_cycles(steps)
        if cycle:
            raise WorkflowValidationError(
                f"Cycle detected: {' → '.join(cycle)}"
            )
        remaining = set(steps) - set(result)
        raise WorkflowValidationError(
            f"Cycle detected involving steps: {sorted(remaining)}"
        )

    # Assert all dependencies appear before dependents
    position = {sid: i for i, sid in enumerate(result)}
    for sid, step in steps.items():
        for dep in step.depends_on:
            if position[dep] >= position[sid]:
                raise WorkflowValidationError(
                    f"Internal error: topological order violated for {dep!r} → {sid!r}"
                )

    return result


def _detect_cycles(steps: Dict[str, WorkflowStep]) -> Optional[List[str]]:
    """Return a cycle path if one exists, otherwise None."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {sid: WHITE for sid in steps}
    path: List[str] = []

    def dfs(node: str, **kw) -> Optional[List[str]]:
        color[node] = GRAY
        path.append(node)
        for dep in steps[node].depends_on:
            if dep not in color:
                continue
            if color[dep] == GRAY:
                # Found cycle — return the cycle path
                cycle_start = path.index(dep)
                return path[cycle_start:] + [dep]
            if color[dep] == WHITE:
                result = dfs(dep)
                if result:
                    return result
        path.pop()
        color[node] = BLACK
        return None

    for sid in steps:
        if color[sid] == WHITE:
            result = dfs(sid)
            if result:
                return result
    return None


# ── Public API ───────────────────────────────────────────────────────────
def workflow_define(
    name: str,
    steps: List[Dict[str, Any]],
    *,
    validate: bool = True,
) -> WorkflowDefinition:
    """Register (or update) a named workflow definition.

    Args:
        name: Unique workflow name (e.g. ``"deploy"``, ``"ci-pipeline"``).
        steps: List of step dicts.  Each dict accepts these keys:

               ``id`` (str, **required**)
                   Unique step identifier within the workflow.
               ``command`` or ``tool`` (str or dict, **required**)
                   The action to execute.  ``command`` is a shell string;
                   ``tool`` is a dict ``{"name": "...", "args": {...}}``.
                   Exactly one of ``command``/``tool`` must be provided.
               ``depends_on`` (list[str], optional)
                   Other step ids that must finish successfully first.
               ``timeout`` (float, optional)
                   Max seconds for this step (default: 300).
               ``retry`` (int, optional)
                   Retry attempts on failure (default: 0).
               ``retry_delay`` (float, optional)
                   Base backoff delay in seconds (default: 2.0).
               ``cwd`` (str, optional)
                   Working directory.
               ``env`` (dict, optional)
                   Extra environment variables.

        validate: If True (default), run structural validation immediately.

    Returns:
        The registered :class:`WorkflowDefinition`.

    Raises:
        WorkflowValidationError: If the definition is structurally invalid.

    Example::

        workflow_define("ci", [
            {"id": "lint", "command": "ruff check .", "timeout": 30},
            {"id": "test", "command": "pytest", "depends_on": ["lint"]},
        ])
    """
    if not name or not isinstance(name, str):
        raise WorkflowValidationError("Workflow name must be a non-empty string")

    built: Dict[str, WorkflowStep] = {}
    for i, step_dict in enumerate(steps):
        if not isinstance(step_dict, dict):
            raise WorkflowValidationError(f"Step {i} must be a dict, got {type(step_dict)}")
        if "id" not in step_dict:
            raise WorkflowValidationError(f"Step {i} is missing required 'id' key")
        sid = step_dict["id"]
        if sid in built:
            raise WorkflowValidationError(f"Duplicate step id {sid!r}")
        try:
            built[sid] = WorkflowStep(
                id=sid,
                command=step_dict.get("command"),
                tool=step_dict.get("tool"),
                depends_on=list(step_dict.get("depends_on", [])),
                timeout=float(step_dict.get("timeout", 300)),
                retry=int(step_dict.get("retry", 0)),
                retry_delay=float(step_dict.get("retry_delay", 2.0)),
                cwd=step_dict.get("cwd"),
                env=dict(step_dict.get("env", {})),
            )
        except WorkflowValidationError:
            raise
        except Exception as exc:
            raise WorkflowValidationError(f"Step {sid!r}: {exc}") from exc

    if not built:
        raise WorkflowValidationError("Workflow must contain at least one step")

    if validate:
        _topological_sort(built)

    with _registry_lock:
        wf = WorkflowDefinition(
            name=name,
            steps=built,
            step_order=list(built.keys()),
        )
        _workflows[name] = wf

    logger.info("Workflow %r registered with %d steps", name, len(built))
    return wf


def _build_run(
    name: str,
    context: Dict[str, Any],
) -> WorkflowRun:
    """Validate the definition exists and build a fresh :class:`WorkflowRun`."""
    with _registry_lock:
        if name not in _workflows:
            raise WorkflowNotFoundError(
                f"No workflow named {name!r}. "
                f"Available: {sorted(_workflows.keys())}"
            )
        wf = _workflows[name]

    run_id = uuid.uuid4().hex[:12]
    run = WorkflowRun(
        id=run_id,
        name=name,
        context=context,
        status=RunStatus.PENDING,
        step_results={
            sid: StepResult(step_id=sid)
            for sid in wf.steps
        },
    )
    return run


async def _execute_run(run: WorkflowRun) -> None:
    """Drive a :class:`WorkflowRun` to completion asynchronously."""
    wf = _workflows[run.name]
    steps = wf.steps
    step_order = _topological_sort(steps)

    # ── Track state ─────────────────────────────────────────────────
    completed: Set[str] = set()
    failed: Set[str] = set()
    active: Set[str] = set()

    executor = _step_executor or _default_executor

    run.status = RunStatus.RUNNING
    run.started_at = time.monotonic()

    # ── Main scheduling loop ────────────────────────────────────────
    while len(completed) + len(failed) < len(steps):
        # Determine which steps are ready
        ready: List[str] = []
        for sid in step_order:
            if sid in completed or sid in failed or sid in active:
                continue
            # All dependencies must be in 'completed'
            deps_ok = all(dep in completed for dep in steps[sid].depends_on)
            if deps_ok:
                # If any dependency failed, skip this step
                if any(dep in failed for dep in steps[sid].depends_on):
                    run.step_results[sid].status = StepStatus.SKIPPED
                    failed.add(sid)
                else:
                    ready.append(sid)

        if not ready and not active:
            # Nothing running and nothing ready — we are done
            break

        # Launch ready steps in parallel
        tasks = []
        for sid in ready:
            step = steps[sid]
            result = run.step_results[sid]
            result.status = StepStatus.RUNNING
            result.started_at = time.monotonic()
            result.attempt = 0
            active.add(sid)
            tasks.append(_run_step_with_retry(sid, step, run.context, executor, result))

        if tasks:
            await asyncio.gather(*tasks)

        # After gather, classify results
        for sid in list(active):
            result = run.step_results[sid]
            if result.status in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                completed.add(sid)
                active.discard(sid)
            elif result.status in (StepStatus.FAILED, StepStatus.TIMEOUT):
                failed.add(sid)
                active.discard(sid)
            # If still RUNNING/RETRYING the gather already awaited it,
            # so this shouldn't happen, but guard anyway.
            elif result.status == StepStatus.RETRYING:
                pass  # will be picked up again if retry logic says so
            else:
                completed.add(sid)
                active.discard(sid)

    # Even if some steps are RETRYING due to backoff in _run_step_with_retry,
    # we need to give them a chance. In practice the gather already awaited them.
    # But handle the edge where a step is stuck:
    remaining_retrying = [
        sid for sid, sr in run.step_results.items()
        if sr.status == StepStatus.RETRYING
    ]
    if remaining_retrying:
        # Let any remaining retry tasks finish with one more gather
        retry_tasks = []
        for sid in remaining_retrying:
            step = steps[sid]
            result = run.step_results[sid]
            active.add(sid)
            retry_tasks.append(_run_step_with_retry(sid, step, run.context, executor, result))
        if retry_tasks:
            await asyncio.gather(*retry_tasks)
        for sid in remaining_retrying:
            result = run.step_results[sid]
            if result.status in (StepStatus.SUCCESS,):
                completed.add(sid)
            else:
                failed.add(sid)

    run.finished_at = time.monotonic()

    if failed:
        run.status = RunStatus.FAILED
    else:
        run.status = RunStatus.SUCCESS

    logger.info(
        "Workflow run %s (%s) finished: %s (%.1fs)",
        run.id, run.name, run.status.value, run.elapsed,
    )


async def _run_step_with_retry(
    sid: str,
    step: WorkflowStep,
    context: Dict[str, Any],
    executor: Callable,
    result: StepResult,
) -> None:
    """Execute a single step with retry and exponential backoff."""
    max_attempts = step.retry + 1
    for attempt in range(1, max_attempts + 1):
        result.attempt = attempt
        try:
            out, err = await executor(step, context)
            result.output = out
            result.error = err
            result.status = StepStatus.SUCCESS
            result.finished_at = time.monotonic()
            result.attempts.append({
                "attempt": attempt,
                "status": "success",
                "elapsed": result.elapsed,
            })
            return
        except (StepTimeoutError, StepExecutionError, asyncio.TimeoutError) as exc:
            result.error = str(exc)
            result.attempts.append({
                "attempt": attempt,
                "status": "timeout" if isinstance(exc, (StepTimeoutError, asyncio.TimeoutError)) else "error",
                "error": str(exc),
            })
            if attempt <= step.retry:
                result.status = StepStatus.RETRYING
                delay = step.retry_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Step %r attempt %d/%d failed: %s — retrying in %.1fs",
                    sid, attempt, max_attempts, exc, delay,
                )
                await asyncio.sleep(delay)
            else:
                result.status = (
                    StepStatus.TIMEOUT
                    if isinstance(exc, (StepTimeoutError, asyncio.TimeoutError))
                    else StepStatus.FAILED
                )
                result.finished_at = time.monotonic()
                logger.error(
                    "Step %r failed after %d attempts: %s", sid, attempt, exc,
                )
                return
        except Exception as exc:
            result.error = str(exc)
            result.status = StepStatus.FAILED
            result.finished_at = time.monotonic()
            result.attempts.append({
                "attempt": attempt,
                "status": "error",
                "error": str(exc),
            })
            logger.exception("Step %r unexpected error", sid)
            return


# ── Foreground runner (blocking) ─────────────────────────────────────────
def _run_in_foreground(run: WorkflowRun) -> WorkflowRun:
    """Run a workflow synchronously (blocking call).

    Uses the running event loop if one exists; otherwise creates one.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # We're inside an async context — schedule and wait
        import concurrent.futures
        future = asyncio.run_coroutine_threadsafe(_execute_run(run), loop)
        future.result()
    else:
        asyncio.run(_execute_run(run))
    return run


# ── Background runner ────────────────────────────────────────────────────
_background_loop: Optional[asyncio.AbstractEventLoop] = None
_bg_thread: Optional[threading.Thread] = None
_bg_lock = threading.Lock()


def _ensure_background_loop() -> asyncio.AbstractEventLoop:
    """Lazily start a background asyncio event loop for non-blocking runs."""
    global _background_loop, _bg_thread
    with _bg_lock:
        if _background_loop is None or _background_loop.is_closed():
            _background_loop = asyncio.new_event_loop()
            _bg_thread = threading.Thread(
                target=_background_loop.run_forever,
                name="meshctx-workflow-bg",
                daemon=True,
            )
            _bg_thread.start()
        return _background_loop


def workflow_run(
    name: str,
    context: Optional[Dict[str, Any]] = None,
    *,
    blocking: bool = True,
    on_complete: Optional[Callable[[WorkflowRun], Any]] = None,
) -> str:
    """Execute a previously defined workflow and return its run id.

    Args:
        name: Name of a registered workflow (see :func:`workflow_define`).
        context: Arbitrary dict passed through to each step.  Scalar values
                 are injected as environment variables (``WF_<KEY>``).
        blocking: If True (default), block until the workflow completes.
                  If False, schedule on a background event loop and return
                  immediately.
        on_complete: Optional callback invoked with the completed
                     :class:`WorkflowRun` when the run finishes.  Only
                     meaningful when ``blocking=False``.

    Returns:
        The run id (a short hex string).  Use :func:`workflow_status` to
        check progress.

    Raises:
        WorkflowNotFoundError: If *name* was never defined.
    """
    ctx = dict(context or {})
    run = _build_run(name, ctx)

    with _registry_lock:
        _runs[run.id] = run

    if blocking:
        _run_in_foreground(run)
        if on_complete:
            on_complete(run)
    else:
        loop = _ensure_background_loop()

        import concurrent.futures as cf

        def _done_callback(fut: cf.Future, **kw) -> None:
            try:
                fut.result()
            except Exception:
                logger.exception("Background workflow run %s error", run.id)
            if on_complete:
                on_complete(run)

        fut = asyncio.run_coroutine_threadsafe(_execute_run(run), loop)
        fut.add_done_callback(_done_callback)

    return run.id


def workflow_status(run_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve the current state of a workflow run.

    Args:
        run_id: The id returned by :func:`workflow_run`.

    Returns:
        A dict with keys ``id``, ``name``, ``status``, ``context``,
        ``started_at``, ``finished_at``, ``elapsed``, and ``steps`` (a dict
        of step-id → step-status dicts).  Returns ``None`` if the run id
        is unknown.

    Example::

        >>> status = workflow_status("abc123def456")
        >>> status["status"]
        'running'
        >>> status["steps"]["lint"]["status"]
        'success'
    """
    with _registry_lock:
        run = _runs.get(run_id)
    if run is None:
        return None
    return run.to_dict()


def workflow_cancel(run_id: str) -> bool:
    """Cancel a running workflow (best-effort).

    Currently sets the run status to CANCELLED; active steps may still
    complete.  Returns True if the run was found and cancelled, False if
    it was not found or already finished.
    """
    with _registry_lock:
        run = _runs.get(run_id)
    if run is None:
        return False
    if run.status not in (RunStatus.PENDING, RunStatus.RUNNING):
        return False
    run.status = RunStatus.CANCELLED
    run.finished_at = time.monotonic()
    logger.info("Workflow run %s cancelled", run_id)
    return True


def workflow_list() -> List[Dict[str, Any]]:
    """List all registered workflow definitions."""
    with _registry_lock:
        return [
            {
                "name": wf.name,
                "step_count": len(wf.steps),
                "steps": list(wf.steps.keys()),
            }
            for wf in _workflows.values()
        ]


def workflow_delete(name: str) -> bool:
    """Delete a workflow definition.  Returns True if it existed."""
    with _registry_lock:
        if name in _workflows:
            del _workflows[name]
            logger.info("Workflow %r deleted", name)
            return True
        return False


def workflow_runs() -> List[Dict[str, Any]]:
    """List all workflow runs (active and completed)."""
    with _registry_lock:
        return [run.to_dict() for run in _runs.values()]


def workflow_stats() -> Dict[str, Any]:
    """Return aggregate statistics about the workflow engine."""
    with _registry_lock:
        total_runs = len(_runs)
        status_counts: Dict[str, int] = {}
        for run in _runs.values():
            s = run.status.value
            status_counts[s] = status_counts.get(s, 0) + 1
        return {
            "definitions": len(_workflows),
            "total_runs": total_runs,
            "runs_by_status": status_counts,
            "definitions_list": sorted(_workflows.keys()),
        }
