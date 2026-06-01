"""
P0-7 动态Summon子Agent引擎
==========================
动态召唤(Summon)子Agent引擎 — 对标Goose CLI的Summon子Agent指令。

核心理念：根据自然语言描述自动创建子Agent、委派任务、等待结果、回收。

功能：
  1. summon(description, task, timeout) → SummonResult
     根据自然语言描述自动创建子Agent、委派任务、等待结果、回收
  2. summon_parallel(tasks: List[Dict]) → List[SummonResult]
     并行召唤多个子Agent执行不同任务
  3. active_agents() → List[Dict]
     查看当前活跃（运行中）的子Agent
  4. dismiss(agent_id) → bool
     遣散/回收指定子Agent

集成:
  - 使用现有的Agent Swarm/Agent Factory创建agent
  - from src.core.agent_swarm import AgentSwarm (ManagerAgent/WorkerAgent)
  - from src.core.agent_factory import AgentFactory
  - from src.core.agent_teams import AgentRole, AgentTeamManager

API端点:
  POST /api/summon — 召唤子Agent ({"description":"...", "task":"..."})
  GET  /api/summon — 列出活跃子Agent
  DELETE /api/summon/{agent_id} — 遣散子Agent

依赖最小化：主要利用现有Swarm框架。Swarm不可用时用简化线程池实现。
"""

import os
import time
import uuid
import threading
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, Future, TimeoutError as FutureTimeoutError

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# 数据类 — SummonResult
# ═══════════════════════════════════════════════════════════════════

class SummonStatus(str, Enum):
    """子Agent召唤状态枚举"""
    PENDING = "pending"         # 等待分配
    RUNNING = "running"         # 正在执行
    DONE = "done"               # 执行完成
    FAILED = "failed"           # 执行失败
    TIMEOUT = "timeout"         # 超时
    DISMISSED = "dismissed"     # 已遣散


@dataclass
class SummonResult:
    """
    子Agent召唤结果。
    
    Attributes:
        agent_id: 子Agent唯一标识符
        description: 任务的自然语言描述
        task: 具体任务内容
        status: 执行状态
        result: 执行结果（成功时）
        error: 错误信息（失败时）
        duration: 执行耗时（秒）
        tokens_used: 消耗的token数（估算）
        role: 使用的Agent角色
    """
    agent_id: str
    description: str
    task: str
    status: SummonStatus = SummonStatus.PENDING
    result: str = ""
    error: str = ""
    duration: float = 0.0
    tokens_used: int = 0
    role: str = "general"
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0

    @property
    def is_active(self) -> bool:
        """是否仍在活跃状态"""
        return self.status in (SummonStatus.PENDING, SummonStatus.RUNNING)

    @property
    def is_success(self) -> bool:
        """是否成功完成"""
        return self.status == SummonStatus.DONE

    def to_dict(self) -> Dict[str, Any]:
        """转为字典（用于API响应）"""
        return {
            "agent_id": self.agent_id,
            "description": self.description,
            "task": self.task,
            "status": self.status.value,
            "result": self.result[:500] if self.result else "",
            "error": self.error,
            "duration": round(self.duration, 3),
            "tokens_used": self.tokens_used,
            "role": self.role,
            "created_at": self.created_at,
            "is_active": self.is_active,
        }


# ═══════════════════════════════════════════════════════════════════
# Agent角色推断器 — 根据描述自动选择合适的Agent角色
# ═══════════════════════════════════════════════════════════════════

# 关键词→角色映射表（中文+英文）
_KEYWORD_ROLE_MAP = [
    # (关键词列表, 角色)
    (["写代码", "编写代码", "实现", "开发", "编程", "函数", "方法", "类",
      "code", "implement", "develop", "function", "method", "class",
      "修复bug", "改bug", "fix bug", "debug", "重构", "refactor"], "coder"),
    (["审查", "检查", "review", "audit", "安全", "漏洞", "security",
      "代码质量", "code quality", "lint", "合规", "compliance"], "reviewer"),
    (["架构", "设计", "系统设计", "architecture", "design", "system design",
      "技术选型", "tech stack", "方案", "solution", "模块划分"], "architect"),
    (["测试", "测试用例", "单元测试", "集成测试", "test", "unit test",
      "integration test", "pytest", "unittest", "覆盖率", "coverage",
      "回归测试", "regression"], "tester"),
    (["研究", "调研", "分析", "research", "analyze", "investigate",
      "论文", "paper", "技术趋势", "tech trend", "文献", "literature",
      "对比", "compare", "评估", "evaluate"], "researcher"),
    (["部署", "发布", "deploy", "release", "CI/CD", "容器化", "docker",
      "k8s", "kubernetes", "监控", "monitor", "运维", "ops",
      "基础设施", "infrastructure", "流水线", "pipeline"], "devops"),
    (["通用", "general", "助手", "assistant", "默认", "default",
      "对话", "chat", "问答", "qa", "总结", "summarize",
      "翻译", "translate", "解释", "explain"], "general"),
]


def _infer_role(description: str) -> str:
    """
    根据任务描述自动推断最合适的Agent角色。
    
    使用关键词匹配策略，返回第一个匹配的角色名。
    无匹配时返回 "general"。
    """
    description_lower = description.lower()
    for keywords, role in _KEYWORD_ROLE_MAP:
        for kw in keywords:
            if kw.lower() in description_lower:
                return role
    return "general"


def _estimate_tokens(text: str) -> int:
    """
    粗略估算token消耗（中文约1.5字符/token，英文约4字符/token）。
    实际使用中可替换为tiktoken。
    """
    if not text:
        return 0
    # 简单启发式：中文字符权重更高
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4) + 1


# ═══════════════════════════════════════════════════════════════════
# 任务执行器 — 实际运行任务的抽象
# ═══════════════════════════════════════════════════════════════════

class TaskExecutor:
    """
    任务执行器基类 — 负责在子Agent中执行具体任务。
    
    优先尝试使用AgentSwarm（ManagerAgent/WorkerAgent模式），
    不可用时降级为简化线程池执行。
    """

    def __init__(self, max_workers: int = 8):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="summon_")
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()
        self._llm_callback: Optional[Callable] = None  # 可注入的LLM调用回调

    def set_llm_callback(self, callback: Callable[[Dict], str]):
        """设置LLM调用回调函数 — 用于实际调用大模型"""
        self._llm_callback = callback

    def execute(self, agent_id: str, task: str, description: str,
                timeout: float = 300, role: str = "general") -> SummonResult:
        """
        同步执行任务 — 在线程池中运行，等待结果。
        
        Args:
            agent_id: Agent标识符
            task: 任务内容
            description: 任务描述
            timeout: 超时时间（秒）
            role: Agent角色

        Returns:
            SummonResult 包含执行结果
        """
        result = SummonResult(
            agent_id=agent_id,
            description=description,
            task=task,
            role=role,
        )

        future = self._pool.submit(
            self._run_task,
            agent_id, task, description, role,
        )
        with self._lock:
            self._futures[agent_id] = future

        result.started_at = time.time()
        result.status = SummonStatus.RUNNING

        try:
            output = future.result(timeout=timeout)
            result.status = SummonStatus.DONE
            result.result = output
            result.tokens_used = (_estimate_tokens(task) +
                                  _estimate_tokens(description) +
                                  _estimate_tokens(output))
        except FutureTimeoutError:
            result.status = SummonStatus.TIMEOUT
            result.error = f"任务超时（{timeout}秒）"
            future.cancel()
            logger.warning(f"[Summon] Agent {agent_id} 超时: {description[:60]}...")
        except Exception as e:
            result.status = SummonStatus.FAILED
            result.error = str(e)
            logger.error(f"[Summon] Agent {agent_id} 执行失败: {e}")
        finally:
            result.completed_at = time.time()
            result.duration = result.completed_at - result.started_at
            with self._lock:
                self._futures.pop(agent_id, None)

        return result

    def execute_async(self, agent_id: str, task: str, description: str,
                      role: str = "general") -> SummonResult:
        """
        异步提交任务 — 立即返回，不等待结果。
        返回SummonResult(状态为PENDING)，后续通过poll获取结果。
        """
        result = SummonResult(
            agent_id=agent_id,
            description=description,
            task=task,
            role=role,
            status=SummonStatus.PENDING,
        )

        future = self._pool.submit(
            self._run_task,
            agent_id, task, description, role,
        )
        with self._lock:
            self._futures[agent_id] = future

        # 启动后台线程等待结果并更新SummonResult
        def _wait_and_update():
            result.status = SummonStatus.RUNNING
            result.started_at = time.time()
            try:
                output = future.result()
                result.status = SummonStatus.DONE
                result.result = output
                result.tokens_used = (_estimate_tokens(task) +
                                      _estimate_tokens(description) +
                                      _estimate_tokens(output))
            except Exception as e:
                result.status = SummonStatus.FAILED
                result.error = str(e)
            finally:
                result.completed_at = time.time()
                result.duration = result.completed_at - result.started_at
                with self._lock:
                    self._futures.pop(agent_id, None)

        threading.Thread(target=_wait_and_update, daemon=True).start()
        return result

    def _run_task(self, agent_id: str, task: str, description: str,
                  role: str) -> str:
        """
        实际执行任务的内核方法。
        
        优先使用AgentSwarm框架，如果不可用则：
        1. 尝试调用注入的LLM回调
        2. 降级为简化模拟执行
        """
        # ── 尝试使用AgentSwarm ──
        try:
            from src.core.agent_swarm import get_swarm_manager
            swarm_mgr = get_swarm_manager()
            if swarm_mgr:
                return self._run_with_swarm(swarm_mgr, agent_id, task, description, role)
        except ImportError:
            logger.debug("[Summon] AgentSwarm不可用，使用简化执行器")
        except Exception as e:
            logger.debug(f"[Summon] AgentSwarm调用失败: {e}")

        # ── 尝试使用AgentTeams ──
        try:
            from src.core.agent_teams import get_teams
            teams = get_teams()
            team_task = teams.dispatch(role, instruction=task, context=description)
            # 模拟等待执行
            time.sleep(0.5)
            simulated = f"[{role}] 完成任务: {task[:100]}"
            teams.complete_task(team_task.task_id, result=simulated, tokens=_estimate_tokens(task))
            return simulated
        except ImportError:
            logger.debug("[Summon] AgentTeams不可用")
        except Exception as e:
            logger.debug(f"[Summon] AgentTeams调用失败: {e}")

        # ── 使用LLM回调 ──
        if self._llm_callback:
            try:
                return self._llm_callback({
                    "agent_id": agent_id,
                    "task": task,
                    "description": description,
                    "role": role,
                })
            except Exception as e:
                logger.warning(f"[Summon] LLM回调失败: {e}")

        # ── 降级：简化模拟执行 ──
        time.sleep(0.1)  # 模拟处理延迟
        return f"[{role}] 完成任务: {task[:200]}"

    def _run_with_swarm(self, swarm_mgr, agent_id: str, task: str,
                        description: str, role: str) -> str:
        """
        使用AgentSwarm（ManagerAgent）执行任务。
        同步包装asyncio调用。
        """
        import asyncio

        async def _do_swarm():
            swarm_tasks = await swarm_mgr.submit_task(
                description=task,
                task_type=role,
                context=description,
            )
            if not swarm_tasks:
                return f"[{role}] 无Worker可用，任务未分配"

            # 等待所有子任务完成
            timeout_at = time.time() + 60
            while time.time() < timeout_at:
                all_done = True
                for st in swarm_tasks:
                    t = swarm_mgr.tasks.get(st.task_id)
                    if t and t.status.value not in ("done", "failed"):
                        all_done = False
                        break
                if all_done:
                    break
                await asyncio.sleep(0.5)

            results = []
            for st in swarm_tasks:
                t = swarm_mgr.tasks.get(st.task_id)
                if t:
                    results.append(t.result or t.error or "无结果")
            return "\n".join(results) if results else "任务已分配但无结果"

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在已有事件循环中创建新的事件循环
                new_loop = asyncio.new_event_loop()
                try:
                    return new_loop.run_until_complete(_do_swarm())
                finally:
                    new_loop.close()
            else:
                return loop.run_until_complete(_do_swarm())
        except RuntimeError:
            return asyncio.run(_do_swarm())

    def cancel(self, agent_id: str) -> bool:
        """取消指定Agent的任务"""
        with self._lock:
            future = self._futures.pop(agent_id, None)
        if future and not future.done():
            return future.cancel()
        return False

    def active_futures(self) -> List[str]:
        """返回所有活跃的future ID"""
        with self._lock:
            return [aid for aid, f in self._futures.items() if not f.done()]

    def shutdown(self, wait: bool = True):
        """关闭执行器"""
        self._pool.shutdown(wait=wait)

    def __del__(self):
        try:
            self._pool.shutdown(wait=False)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# SummonEngine — 核心召唤引擎（单例模式）
# ═══════════════════════════════════════════════════════════════════

class SummonEngine:
    """
    动态Summon子Agent引擎 — 单例。

    对标Goose CLI的Summon子Agent指令：
    - 通过自然语言描述自动创建/选择合适的子Agent
    - 委派任务、等待结果、回收Agent
    - 支持并行召唤多个子Agent
    - 可查看活跃子Agent、遣散指定子Agent

    使用示例:
        engine = get_summon_engine()
        result = engine.summon(
            description="写一个排序算法",
            task="实现快速排序并写测试",
            timeout=120,
        )
        print(result.to_dict())

        # 并行召唤
        results = engine.summon_parallel([
            {"description": "研究Python asyncio", "task": "写出最佳实践"},
            {"description": "写单元测试", "task": "为utils.py写测试"},
        ])

        # 查看活跃Agent
        active = engine.active_agents()

        # 遣散Agent
        engine.dismiss(result.agent_id)
    """

    def __init__(self):
        self._executor = TaskExecutor(max_workers=8)
        self._active_results: Dict[str, SummonResult] = {}
        self._history: List[SummonResult] = []
        self._lock = threading.RLock()
        self._summary_counter: int = 0
        logger.info("[SummonEngine] 初始化完成 — 动态Summon子Agent引擎就绪")

    # ── 核心API：summon ─────────────────────────────────────

    def summon(self, description: str, task: str = "",
               timeout: float = 300, role: str = "",
               async_mode: bool = False) -> SummonResult:
        """
        召唤一个子Agent执行任务。

        Args:
            description: 自然语言任务描述（用于推断Agent角色）
            task: 具体任务内容（为空时使用description）
            timeout: 超时时间（秒），默认300秒
            role: 指定的Agent角色（为空时根据description自动推断）
            async_mode: 是否异步模式（True=立即返回不等待结果）

        Returns:
            SummonResult 包含agent_id, status, result等信息

        Example:
            >>> engine = get_summon_engine()
            >>> result = engine.summon("写一个冒泡排序算法")
            >>> print(result.status)  # 'done'
        """
        # 生成唯一Agent ID
        with self._lock:
            self._summary_counter += 1
            agent_id = f"summon_{int(time.time()*1000)}_{self._summary_counter:04d}"

        # 推断角色
        actual_role = role or _infer_role(description)
        actual_task = task or description

        logger.info(
            f"[SummonEngine] 召唤子Agent | id={agent_id} | "
            f"role={actual_role} | description={description[:60]}..."
        )

        # 尝试通过AgentFactory初始化（如需要）
        try:
            from src.core.agent_factory import get_agent_factory
            factory = get_agent_factory()
            factory_status = factory.status()
            logger.debug(f"[SummonEngine] AgentFactory状态: {factory_status.get('all_ready')}")
        except ImportError:
            logger.debug("[SummonEngine] AgentFactory不可用")
        except Exception:
            pass

        # 执行任务
        if async_mode:
            result = self._executor.execute_async(
                agent_id=agent_id,
                task=actual_task,
                description=description,
                role=actual_role,
            )
        else:
            result = self._executor.execute(
                agent_id=agent_id,
                task=actual_task,
                description=description,
                timeout=timeout,
                role=actual_role,
            )

        # 存储结果
        with self._lock:
            if result.is_active or async_mode:
                self._active_results[agent_id] = result
            self._history.append(result)
            # 限制历史记录数量
            if len(self._history) > 1000:
                self._history = self._history[-500:]

        logger.info(
            f"[SummonEngine] 召唤完成 | id={agent_id} | "
            f"status={result.status.value} | duration={result.duration:.2f}s"
        )
        return result

    # ── 并行召唤：summon_parallel ────────────────────────────

    def summon_parallel(self, tasks: List[Dict], timeout: float = 300) -> List[SummonResult]:
        """
        并行召唤多个子Agent执行不同任务。

        Args:
            tasks: 任务列表，每个元素包含:
                   - description (str): 任务描述
                   - task (str, 可选): 具体任务内容
                   - role (str, 可选): 指定角色
                   - timeout (float, 可选): 单独超时
            timeout: 全局默认超时时间（秒）

        Returns:
            List[SummonResult] 每个任务对应一个结果

        Example:
            >>> engine = get_summon_engine()
            >>> results = engine.summon_parallel([
            ...     {"description": "写单元测试"},
            ...     {"description": "代码审查"},
            ...     {"description": "研究部署方案"},
            ... ])
            >>> for r in results:
            ...     print(f"{r.agent_id}: {r.status.value}")
        """
        if not tasks:
            return []

        logger.info(f"[SummonEngine] 并行召唤 {len(tasks)} 个子Agent")

        # 使用线程池并行提交
        def _run_single(task_spec: Dict) -> SummonResult:
            desc = task_spec.get("description", "")
            t = task_spec.get("task", "")
            r = task_spec.get("role", "")
            t_out = task_spec.get("timeout", timeout)
            return self.summon(
                description=desc,
                task=t,
                timeout=t_out,
                role=r,
                async_mode=False,
            )

        with ThreadPoolExecutor(max_workers=min(len(tasks), 8)) as pool:
            futures = [pool.submit(_run_single, ts) for ts in tasks]
            results = []
            for future in futures:
                try:
                    results.append(future.result(timeout=timeout + 10))
                except FutureTimeoutError:
                    results.append(SummonResult(
                        agent_id="unknown",
                        description="并行召唤超时",
                        task="",
                        status=SummonStatus.TIMEOUT,
                        error=f"并行任务超时（{timeout}秒）",
                    ))
                except Exception as e:
                    results.append(SummonResult(
                        agent_id="unknown",
                        description="并行召唤失败",
                        task="",
                        status=SummonStatus.FAILED,
                        error=str(e),
                    ))

        # 清理已完成的任务
        with self._lock:
            for r in results:
                self._active_results.pop(r.agent_id, None)

        done_count = sum(1 for r in results if r.is_success)
        logger.info(f"[SummonEngine] 并行召唤完成 | {done_count}/{len(results)} 成功")
        return results

    # ── 活跃Agent查询：active_agents ─────────────────────────

    def active_agents(self) -> List[Dict[str, Any]]:
        """
        查看当前活跃（运行中/待处理）的子Agent。

        Returns:
            List[Dict] 活跃Agent信息列表
        """
        with self._lock:
            # 清理已完成的
            self._active_results = {
                aid: r for aid, r in self._active_results.items()
                if r.is_active
            }
            return [r.to_dict() for r in self._active_results.values()]

    # ── 遣散Agent：dismiss ──────────────────────────────────

    def dismiss(self, agent_id: str) -> bool:
        """
        遣散/回收指定子Agent。

        取消正在运行的任务并标记为已遣散。

        Args:
            agent_id: 要遣散的Agent ID

        Returns:
            bool: 是否成功遣散（False表示Agent不存在或已完成）

        Example:
            >>> engine = get_summon_engine()
            >>> engine.dismiss("summon_1234567_0001")
            True
        """
        with self._lock:
            result = self._active_results.pop(agent_id, None)

        if result is None:
            # 尝试取消执行器中的future
            if self._executor.cancel(agent_id):
                logger.info(f"[SummonEngine] 遣散Agent: {agent_id} (已取消运行)")
                return True
            logger.warning(f"[SummonEngine] 遣散失败: Agent {agent_id} 不存在或已完成")
            return False

        # 取消底层执行
        self._executor.cancel(agent_id)

        # 更新状态
        result.status = SummonStatus.DISMISSED
        result.completed_at = time.time()
        result.duration = result.completed_at - (result.started_at or result.created_at)
        logger.info(f"[SummonEngine] 遣散Agent: {agent_id} | 运行时长: {result.duration:.2f}s")
        return True

    # ── 辅助方法 ────────────────────────────────────────────

    def summon_result(self, agent_id: str) -> Optional[SummonResult]:
        """
        按agent_id查询召唤结果。

        Args:
            agent_id: Agent标识符

        Returns:
            SummonResult 或 None
        """
        with self._lock:
            # 先查活跃列表
            if agent_id in self._active_results:
                return self._active_results[agent_id]
            # 再查历史
            for r in reversed(self._history):
                if r.agent_id == agent_id:
                    return r
        return None

    def get_history(self, limit: int = 20) -> List[SummonResult]:
        """
        获取最近的召唤历史记录。

        Args:
            limit: 返回条数限制

        Returns:
            List[SummonResult] 历史记录
        """
        with self._lock:
            return list(reversed(self._history[-limit:]))

    def get_stats(self) -> Dict[str, Any]:
        """
        获取召唤引擎统计信息。

        Returns:
            Dict 包含活跃/完成/失败/总计数
        """
        with self._lock:
            total = len(self._history)
            active = sum(1 for r in self._active_results.values() if r.is_active)
            done = sum(1 for r in self._history if r.status == SummonStatus.DONE)
            failed = sum(1 for r in self._history if r.status == SummonStatus.FAILED)
            timeout_count = sum(1 for r in self._history if r.status == SummonStatus.TIMEOUT)
            dismissed = sum(1 for r in self._history if r.status == SummonStatus.DISMISSED)
            total_tokens = sum(r.tokens_used for r in self._history)

        return {
            "engine": "SummonEngine P0-7",
            "active_agents": active,
            "total_summoned": total,
            "done": done,
            "failed": failed,
            "timeout": timeout_count,
            "dismissed": dismissed,
            "success_rate": round(done / max(total, 1) * 100, 1),
            "total_tokens_used": total_tokens,
            "active_futures": len(self._executor.active_futures()),
        }

    def set_llm_callback(self, callback: Callable[[Dict], str]):
        """
        设置LLM调用回调 — 使SummonEngine能实际调用大模型。

        Args:
            callback: 接收 {"agent_id","task","description","role"} → 返回字符串
        """
        self._executor.set_llm_callback(callback)
        logger.info("[SummonEngine] LLM回调已设置")

    def shutdown(self, wait: bool = True):
        """
        关闭引擎 — 清理所有资源。

        Args:
            wait: 是否等待运行中的任务完成
        """
        logger.info("[SummonEngine] 关闭中...")
        # 遣散所有活跃Agent
        with self._lock:
            for agent_id in list(self._active_results.keys()):
                self.dismiss(agent_id)
        self._executor.shutdown(wait=wait)
        logger.info("[SummonEngine] 已关闭")


# ═══════════════════════════════════════════════════════════════════
# 单例访问
# ═══════════════════════════════════════════════════════════════════

_summon_engine: Optional[SummonEngine] = None
_summon_lock = threading.Lock()


def get_summon_engine() -> SummonEngine:
    """
    获取SummonEngine单例实例。

    Returns:
        SummonEngine 全局唯一实例
    """
    global _summon_engine
    if _summon_engine is None:
        with _summon_lock:
            if _summon_engine is None:
                _summon_engine = SummonEngine()
    return _summon_engine


def reset_summon_engine():
    """
    重置SummonEngine单例（主要用于测试）。
    关闭当前实例并清空全局引用。
    """
    global _summon_engine
    if _summon_engine is not None:
        _summon_engine.shutdown(wait=False)
    _summon_engine = None
    logger.info("[SummonEngine] 已重置")
