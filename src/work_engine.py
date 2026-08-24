"""meshctx work — 自主工作模式引擎 (v3.120.0)

按任务量持续自主工作 5–24 小时：
  目标 → LLM 拆解子任务 → 逐个执行(复用 run_agent_loop) → 原子落盘 → 断点续跑 → 到期总结。

设计来源: meshctx-work-plan-v0.2（004meshctx 审计通过）
- 子任务墙钟自适应: task_wall = clamp(hours*3600/len(plan)*2, 1200, 7200)
- 软截止+硬兜底: deadline 后不再启动新任务；运行中任务允许收尾，硬截止由 wall_clock 兜底
- 重试分层: 5xx/网络/超时重试3次+指数退避；401/403跳过；429按Retry-After重试1次；业务失败记录
- last_heartbeat 判死: running 但 heartbeat 超时 → resume 时标记 pending 重跑
- 进程锁: pid 文件 O_EXCL 防并发 resume
- max-cost: 达到先落盘再停；总结 LLM 失败降级为已落盘 result 结构化拼接
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

WORK_DIR = Path.home() / ".meshctx" / "work"
TASK_WALL_MIN = 1200          # 子任务墙钟下限 20min（安全下限，防单点卡死）
TASK_WALL_MAX = 7200          # 子任务墙钟上限 2h
DEADLINE_GRACE = 600          # 软截止容忍 10min
HEARTBEAT_TIMEOUT = 120       # running 但 heartbeat 超时 → 判死重跑
COST_PER_TASK_EST = 20000     # 每子任务粗算 token（v0.1 粗算：attempts×子任务数×估算）
PLAN_CONFIRM_SECONDS = 5      # print-plan-then-go 倒计时
# action_gate 高危工具（发布包内闭源真身有完整白名单；开源 stub 环境优雅降级）
HIGH_RISK_TOOLS = {"run_cmd", "terminal", "browser_navigate", "remote_exec", "write_file"}

_PLAN_SYSTEM = (
    "你是任务规划器。把用户目标拆解成 5–50 个可独立执行的子任务，"
    "每个子任务应是单步可完成的（不依赖其他子任务先完成）。"
    '只输出 JSON 数组，格式: [{"title":"简短标题","detail":"给执行者的具体指令"}]，'
    "不要输出任何其他文字。"
)

_TASK_SYSTEM = (
    "你是 meshctx 自主工作模式的任务执行者。当前只负责完成这一个子任务。"
    "需要读文件/执行命令/搜索时直接使用工具，最后输出简洁的成果总结。"
)


@dataclass
class WorkTask:
    id: str
    title: str
    detail: str
    status: str = "pending"       # pending/running/done/failed/skipped
    attempts: int = 0
    max_attempts: int = 3
    result: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorkJob:
    id: str
    goal: str
    target_hours: float
    deadline_ts: float
    status: str = "pending"       # pending/running/paused/done/failed
    plan: List[WorkTask] = field(default_factory=list)
    summary: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_heartbeat: float = 0.0
    max_cost: int = 0
    cost_estimate: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WorkJob":
        d = dict(d)
        d["plan"] = [WorkTask(**t) if not isinstance(t, WorkTask) else t for t in d.get("plan", [])]
        return cls(**d)


# ── 落盘（原子写 tmp+rename）──────────────────────────────

def _atomic_write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save_job(job: WorkJob) -> Path:
    job.updated_at = time.time()
    p = WORK_DIR / f"{job.id}.json"
    _atomic_write(p, job.to_dict())
    return p


def load_job(job_id: str) -> Optional[WorkJob]:
    p = WORK_DIR / f"{job_id}.json"
    if not p.exists():
        return None
    try:
        return WorkJob.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def list_jobs() -> List[WorkJob]:
    if not WORK_DIR.exists():
        return []
    jobs = []
    for p in sorted(WORK_DIR.glob("*.json")):
        try:
            jobs.append(WorkJob.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return jobs


def _heartbeat(job: WorkJob):
    job.last_heartbeat = time.time()
    save_job(job)


# ── 墙钟自适应（004 审计①）───────────────────────────────

def task_wall_seconds(job: WorkJob) -> int:
    """task_wall = clamp(hours*3600/len(plan)*2, 1200, 7200)"""
    n = max(1, len(job.plan))
    est = int(job.target_hours * 3600 / n * 2)
    return max(TASK_WALL_MIN, min(TASK_WALL_MAX, est))


# ── 重试分层（004 审计③）──────────────────────────────────

def classify_error(text: str) -> str:
    """返回: retry / auth / rate_limit / business"""
    t = (text or "").lower()
    if any(k in t for k in ("401", "403", "invalid api key", "unauthorized", "authentication")):
        return "auth"
    if any(k in t for k in ("429", "rate limit", "rate_limit", "too many requests")):
        return "rate_limit"
    if any(k in t for k in ("timed out", "timeout", "超时", "connection", "refused", "reset",
                            "连接", "拒绝", " 5", "50", "52", "53", "54", "500", "502", "503", "504",
                            "service unavailable", "internal server error", "network")):
        return "retry"
    return "business"


def backoff_seconds(attempt: int) -> float:
    """指数退避 1s/3s/9s + 抖动"""
    return (3 ** attempt) + random.uniform(0, 0.5)


def retry_after_from(text: str) -> Optional[float]:
    import re
    m = re.search(r"retry[-_]after[^\d]*(\d+)", (text or "").lower())
    return float(m.group(1)) if m else None


# ── 计划分解（LLM，失败降级）──────────────────────────────

def plan_tasks(job: WorkJob, client) -> List[WorkTask]:
    """LLM 拆解子任务；失败/非 JSON → 按句切分兜底。"""
    try:
        resp = client.chat.completions.create(
            model=client._model if hasattr(client, "_model") else None,
            messages=[
                {"role": "system", "content": _PLAN_SYSTEM},
                {"role": "user", "content": f"目标: {job.goal}\n预计总时长: {job.target_hours} 小时"},
            ],
            temperature=0.3,
            max_tokens=4096,
            timeout=120,
        )
        raw = resp.choices[0].message.content or ""
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        tasks = []
        for item in data[:50]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip() or "子任务"
            detail = str(item.get("detail", title)).strip()
            if detail:
                tasks.append(WorkTask(id=uuid.uuid4().hex[:8], title=title, detail=detail))
        if tasks:
            return tasks
    except Exception:
        pass
    # 兜底: 按句号/分号切分
    parts = [s.strip() for s in job.goal.replace("\n", "。").split("。") if len(s.strip()) >= 8]
    if not parts:
        parts = [job.goal]
    return [WorkTask(id=uuid.uuid4().hex[:8], title=f"子任务{i+1}", detail=p) for i, p in enumerate(parts[:50])]


# ── 进程锁（004 补充④）────────────────────────────────────

def acquire_lock(job_id: str) -> Path:
    """pid 文件 O_EXCL；旧 pid 已死则接管。返回锁文件路径。"""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    lock = WORK_DIR / f"{job_id}.lock"
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            return lock
        except FileExistsError:
            try:
                old_pid = int(lock.read_text().strip())
                os.kill(old_pid, 0)          # 进程存在 → 并发 resume 拒绝
                raise RuntimeError(f"job {job_id} 已被 PID {old_pid} 占用（防并发 resume）")
            except ProcessLookupError:
                lock.unlink(missing_ok=True)  # 旧进程已死 → 接管
                continue
            except ValueError:
                lock.unlink(missing_ok=True)
                continue
    raise RuntimeError(f"job {job_id} 锁获取失败")


def release_lock(lock: Path):
    try:
        lock.unlink(missing_ok=True)
    except Exception:
        pass


# ── 单任务执行（复用 run_agent_loop + 分层重试）────────────

def _run_one_task(client, task: WorkTask, wall_clock: int) -> None:
    """执行单个子任务并写回 task 状态（含重试）。"""
    from src.agent_loop import run_agent_loop
    from src.chat_tools import TOOLS_OPENAI, execute_tool

    deadline_soft = None
    while task.attempts < task.max_attempts:
        task.attempts += 1
        task.status = "running"
        task.error = ""
        final = ""
        error_text = ""
        timed_out = False
        try:
            messages = [
                {"role": "system", "content": _TASK_SYSTEM},
                {"role": "user", "content": task.detail},
            ]
            async def _run():
                nonlocal final, error_text, timed_out
                async for ev in run_agent_loop(
                    client, messages,
                    tools=TOOLS_OPENAI,
                    exec_tool=execute_tool,
                    max_rounds=4,
                    wall_clock=float(wall_clock),
                ):
                    if ev["type"] == "token":
                        final += ev["text"]
                    elif ev["type"] == "error":
                        error_text = ev["text"]
                    elif ev["type"] == "timed_out":
                        timed_out = True
                        error_text = ev.get("text", "任务超时")
            asyncio.run(_run())
        except Exception as e:
            error_text = f"{type(e).__name__}: {e}"

        if timed_out:
            error_text = f"子任务墙钟超时（{wall_clock}s）"
        final = final.strip()
        if error_text and not final:
            kind = classify_error(error_text)
            if kind == "auth":
                task.status = "failed"
                task.error = f"[认证错误不重试] {error_text[:200]}"
                return
            if kind == "rate_limit":
                ra = retry_after_from(error_text)
                if ra and task.attempts < task.max_attempts:
                    time.sleep(min(ra, 60))
                    continue
                task.status = "failed"
                task.error = f"[限流跳过] {error_text[:200]}"
                return
            if kind == "retry" and task.attempts < task.max_attempts:
                time.sleep(backoff_seconds(task.attempts))
                continue
            task.status = "failed"
            task.error = f"[业务失败不自动重试] {error_text[:200]}"
            return
        # 成功（有最终文本）或部分输出
        task.status = "done" if final else "failed"
        task.result = final[:4000]
        if not final:
            task.error = error_text[:200] or "无输出"
        return
    task.status = "failed"
    task.error = task.error or f"重试 {task.max_attempts} 次仍失败"
    return


# ── 到期总结（LLM 失败降级拼接，004 补充③）────────────────

def summarize_job(job: WorkJob, client) -> str:
    done = [t for t in job.plan if t.status == "done"]
    failed = [t for t in job.plan if t.status in ("failed", "skipped")]
    try:
        brief = "\n".join(
            f"- {t.title}: {t.result[:300]}" for t in done[:20]
        ) or "（无完成子任务）"
        resp = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "你是工作汇报生成器。基于子任务结果生成结构化工作总结。"},
                {"role": "user", "content": f"目标: {job.goal}\n子任务结果:\n{brief}"},
            ],
            temperature=0.3,
            max_tokens=2048,
            timeout=120,
        )
        s = (resp.choices[0].message.content or "").strip()
        if s:
            return s
    except Exception:
        pass
    lines = [f"目标: {job.goal}"]
    for t in done:
        lines.append(f"✅ {t.title}: {t.result[:200]}")
    for t in failed:
        lines.append(f"❌ {t.title}: {t.error[:150]}")
    lines.append(f"完成 {len(done)}/{len(job.plan)}，失败 {len(failed)}")
    return "\n".join(lines)


# ── 主执行循环 ────────────────────────────────────────────

def run_job(job: WorkJob, report=None) -> WorkJob:
    """顺序执行 job 的子任务，直到完成/到期/成本上限。report: 可选进度回调(line:str)。"""
    from src.model_registry import get_registry
    reg = get_registry()
    client = reg.get()
    if client is None:
        job.status = "failed"
        job.summary = "未配置可用模型（models.entries 无 key）"
        save_job(job)
        return job

    job.status = "running"
    save_job(job)
    tw = task_wall_seconds(job)

    def _log(line: str):
        if report:
            report(line)
        else:
            print(line, flush=True)

    for i, task in enumerate(job.plan):
        if task.status in ("done", "skipped"):
            continue
        # 到期检查: deadline 已过 → 不再启动新任务
        if time.time() >= job.deadline_ts:
            _log(f"⏰ 到期（{job.deadline_ts:.0f}），停止启动新任务")
            break
        # max-cost 检查: 达到先落盘再停
        if job.max_cost and job.cost_estimate >= job.max_cost:
            _log(f"💰 成本上限已达（{job.cost_estimate} token ≥ {job.max_cost}），先落盘再停")
            save_job(job)
            break
        _log(f"[{i+1}/{len(job.plan)}] ▶ {task.title}（墙钟 {tw}s）")
        task.started_at = time.time()
        _run_one_task(client, task, wall_clock=tw)
        task.finished_at = time.time()
        job.cost_estimate += task.attempts * COST_PER_TASK_EST
        _heartbeat(job)
        if task.status == "done":
            _log(f"  ✅ {task.title}（{int(task.finished_at-task.started_at)}s）")
        else:
            _log(f"  ❌ {task.title}: {task.error[:120]}")

    # 到期后若还有任务未做 → 标记 skipped
    for task in job.plan:
        if task.status == "pending":
            task.status = "skipped"
            task.error = "到期未执行"
    save_job(job)

    # 总结（软截止后仍执行，保证必有汇报）
    _log("📄 生成工作总结...")
    job.summary = summarize_job(job, client)
    job.status = "done"
    _heartbeat(job)
    _log("✅ 工作结束")
    return job


# ── resume（004 补充④ 判死 + 锁）─────────────────────────

def recoverable_jobs() -> List[WorkJob]:
    """返回可恢复 job：pending/paused，或 running 但 heartbeat 超时（进程死）"""
    out = []
    for job in list_jobs():
        if job.status in ("pending", "paused"):
            out.append(job)
        elif job.status == "running" and job.last_heartbeat and \
                (time.time() - job.last_heartbeat) > HEARTBEAT_TIMEOUT:
            for t in job.plan:
                if t.status == "running":
                    t.status = "pending"
            job.status = "pending"
            save_job(job)
            out.append(job)
    return out
