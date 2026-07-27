"""
meshctx DreamingAgent — 离线记忆整理 & 自动Skill生成
对标: Anthropic Claude Code "Dreaming" 功能 + Hermes Agent 自我改进闭环

架构:
  1. 定时唤醒 (cron "every 6h" 或 "daily at 3:00")
  2. 扫描最近完成的会话 → 提取任务模式
  3. 成功模式 → 自动生成/更新 SKILL.md
  4. 失败模式 → 记录反模式写入 memory
  5. 记忆合并: 短期→长期记忆的再巩固

这是 P0 生死线功能——没有它，meshctx 每次对话都是"第一天上班的新人"
"""
import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from .kernel import Event, EventPriority, Plugin, PluginInfo
except ImportError:
    from src.core.kernel import Event, EventPriority, Plugin, PluginInfo

logger = logging.getLogger("meshctx.dreaming")


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class TaskPattern:
    """从会话中提取的任务模式"""
    pattern_name: str                # 模式名 (如 "web-scraping")
    description: str                 # 描述
    task_template: str               # 任务模板
    tools_used: List[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    avg_duration: float = 0.0
    common_errors: List[str] = field(default_factory=list)
    best_practice: str = ""
    sample_sessions: List[str] = field(default_factory=list)
    last_seen: float = 0.0

    @property
    def success_rate(self, **kw) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    @property
    def is_reliable(self, **kw) -> bool:
        """模式是否足够可靠，值得自动化为Skill"""
        return self.success_count >= 3 and self.success_rate >= 0.7


@dataclass
class DreamReport:
    """每次 Dreaming 运行的报告"""
    timestamp: float = field(default_factory=time.time)
    sessions_scanned: int = 0
    patterns_found: int = 0
    skills_created: int = 0
    skills_updated: int = 0
    memories_consolidated: int = 0
    anti_patterns_recorded: int = 0
    errors: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# Session 扫描器
# ═══════════════════════════════════════════════════════════

class SessionScanner:
    """扫描 sessions.db 提取任务模式"""

    def __init__(self, db_path: str = None, **kw):
        if db_path is None:
            db_path = os.path.expanduser("~/.meshctx/sessions.db")
        self.db_path = db_path

    def _connect(self, **kw) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_recent_sessions(self, since_hours: int = 24, limit: int = 200
                            ) -> List[Dict]:
        """获取最近完成的会话"""
        cutoff = time.time() - since_hours * 3600
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT s.id, s.title, s.timestamp, s.message_count,
                       fts.content
                FROM sessions s
                LEFT JOIN sessions_fts fts ON fts.rowid = s.id
                WHERE s.timestamp > ?
                ORDER BY s.timestamp DESC
                LIMIT ?
            """, (cutoff, limit)).fetchall()

            result = []
            for row in rows:
                d = dict(row)
                # 只分析有足够消息的会话
                if d['message_count'] and d['message_count'] >= 4:
                    result.append(d)
            return result
        finally:
            conn.close()

    def get_session_messages(self, session_id: str, **kw) -> List[Dict]:
        """获取会话消息（从 agent_loop 存储的结构）"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT content FROM sessions_fts WHERE rowid = ?",
                (session_id,)
            ).fetchone()
            if not row:
                return []
            content = row[0] or ""
            messages = []
            for line in content.split("\n"):
                if line.startswith("[user]"):
                    messages.append({"role": "user", "content": line[7:]})
                elif line.startswith("[assistant]"):
                    messages.append({"role": "assistant", "content": line[12:]})
                elif line.startswith("[tool]"):
                    messages.append({"role": "tool", "content": line[7:]})
            return messages
        finally:
            conn.close()


# ═══════════════════════════════════════════════════════════
# 模式提取器
# ═══════════════════════════════════════════════════════════

class PatternExtractor:
    """从会话中提取任务模式——无需LLM的启发式提取"""

    # 已知工具集——用于匹配
    KNOWN_TOOLS = {
        "web_search", "web_extract", "browser_navigate", "browser_click",
        "browser_snapshot", "browser_vision", "browser_type", "browser_scroll",
        "terminal", "read_file", "write_file", "patch", "search_files",
        "execute_code", "delegate_task", "cronjob", "memory",
        "skill_view", "skill_manage", "skills_list", "image_generate",
        "text_to_speech", "vision_analyze", "session_search",
        "process", "clarify", "todo",
    }

    # 关键词 → 模式映射
    PATTERN_SIGNATURES = {
        "web-scraping": {"web_extract", "web_search", "browser_navigate"},
        "file-operation": {"read_file", "write_file", "patch", "search_files"},
        "code-execution": {"terminal", "execute_code", "delegate_task"},
        "github-management": {"terminal", "browser_navigate", "write_file"},
        "research-analysis": {"web_search", "web_extract", "execute_code"},
        "browser-automation": {"browser_navigate", "browser_click", "browser_type", "browser_snapshot"},
        "memory-management": {"memory", "session_search"},
        "skill-creation": {"skill_view", "skill_manage", "skills_list"},
        "image-generation": {"image_generate", "vision_analyze"},
        "cron-scheduling": {"cronjob"},
        "multi-agent-delegation": {"delegate_task"},
        "disk-scanner": {"terminal", "search_files"},
    }

    def extract_patterns(self, sessions: List[Dict]
                         ) -> List[TaskPattern]:
        """从会话列表中提取聚合模式"""
        patterns: Dict[str, TaskPattern] = {}

        for session in sessions:
            content = session.get("content") or ""
            messages = content.split("\n")
            user_messages = [
                m[7:] for m in messages
                if m.startswith("[user]")
            ]

            # 提取使用的工具
            tools = set()
            for tool in self.KNOWN_TOOLS:
                if tool in content:
                    tools.add(tool)

            # 匹配模式类型
            matched_pattern = None
            for pname, sig_tools in self.PATTERN_SIGNATURES.items():
                if len(tools & sig_tools) >= 2:  # 至少2个工具匹配
                    matched_pattern = pname
                    break

            if not matched_pattern:
                if "web_search" in tools or "browser" in tools:
                    matched_pattern = "research-analysis"
                elif "terminal" in tools:
                    matched_pattern = "code-execution"
                elif "write_file" in tools or "patch" in tools:
                    matched_pattern = "file-operation"
                else:
                    continue  # 无法分类

            # 判断成功/失败（启发式）
            # 成功: 最后有 [assistant] 消息，不含 "error"/"failed"/"blocked"
            has_error = any(
                kw in (messages[-5:] and "\n".join(messages[-5:]) or "").lower()
                for kw in ["error", "failed", "blocked", "not found", "401", "403", "500"]
            )
            is_success = not has_error

            # 聚合到模式
            if matched_pattern not in patterns:
                patterns[matched_pattern] = TaskPattern(
                    pattern_name=matched_pattern,
                    description=self._describe_pattern(matched_pattern),
                )

            p = patterns[matched_pattern]
            if is_success:
                p.success_count += 1
            else:
                p.failure_count += 1

            p.tools_used = list(set(p.tools_used) | tools)
            p.sample_sessions.append(session.get("id", "")[:20])
            p.last_seen = session.get("timestamp", time.time())

            # 提取常见错误
            if not is_success and "error" in content.lower():
                # 提取错误片段
                for line in reversed(messages):
                    if "error" in line.lower() or "failed" in line.lower():
                        err = re.sub(r'\[.*?\]\s*', '', line)[:200]
                        if err not in p.common_errors:
                            p.common_errors.append(err)
                        break

        # 过滤出有意义的模式（至少2次）
        return [p for p in patterns.values()
                if p.success_count + p.failure_count >= 2]

    def _describe_pattern(self, name: str, **kw) -> str:
        descriptions = {
            "web-scraping": "网页抓取与内容提取",
            "file-operation": "文件读写与代码修改",
            "code-execution": "代码执行与脚本运行",
            "github-management": "GitHub仓库管理与操作",
            "research-analysis": "搜索研究与分析总结",
            "browser-automation": "浏览器自动化交互",
            "memory-management": "记忆存取与管理",
            "skill-creation": "Skill创建与管理",
            "image-generation": "图片生成与视觉分析",
            "cron-scheduling": "定时任务调度",
            "multi-agent-delegation": "多Agent任务委派",
            "disk-scanner": "文件系统扫描与搜索",
        }
        return descriptions.get(name, f"{name} 模式")


# ═══════════════════════════════════════════════════════════
# Skill 生成器
# ═══════════════════════════════════════════════════════════

class SkillGenerator:
    """从 TaskPattern 自动生成 SKILL.md"""

    def __init__(self, skills_dir: str = None, **kw):
        if skills_dir is None:
            skills_dir = os.path.expanduser("~/.hermes/profiles/meshctx/skills/")
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def generate_skill_md(self, pattern: TaskPattern, **kw) -> str:
        """生成 SKILL.md 内容"""
        tools_str = ", ".join(sorted(pattern.tools_used))
        errors_section = ""
        if pattern.common_errors:
            errors_section = "\n## 常见陷阱\n" + "\n".join(
                f"- {e[:200]}" for e in pattern.common_errors[:5]
            )

        best_practice = self._best_practice_for(pattern.pattern_name)

        return f"""---
name: {pattern.pattern_name}
version: 1.0.0
auto_generated: true
created_at: {datetime.now().isoformat()}
success_rate: {pattern.success_rate:.0%}
sample_count: {pattern.success_count + pattern.failure_count}
updated_at: {datetime.now().isoformat()}
---

# {pattern.pattern_name}

{pattern.description}

> 🤖 由 DreamingAgent 自动生成 — 基于 {pattern.success_count} 次成功操作

## 触发条件
当用户请求涉及 {pattern.description} 时自动加载

## 步骤

{chr(10).join(f"{i+1}. {step}" for i, step in enumerate(self._generate_steps(pattern)))}

## 推荐工具
{tools_str}

## 最佳实践
{best_practice}
{errors_section}

## 统计
- 总执行次数: {pattern.success_count + pattern.failure_count}
- 成功率: {pattern.success_rate:.0%}
- 最后使用: {datetime.fromtimestamp(pattern.last_seen).isoformat()}
"""
    def _generate_steps(self, pattern: TaskPattern, **kw) -> List[str]:
        """根据模式类型生成步骤"""
        step_templates = {
            "web-scraping": [
                "使用 web_search 进行初步检索",
                "使用 web_extract 提取目标页面内容",
                "用 Python 解析并清洗数据",
                "将结果写入文件或返回用户",
            ],
            "file-operation": [
                "使用 read_file 查看目标文件当前状态",
                "使用 search_files 定位相关文件",
                "使用 patch 或 write_file 进行修改",
                "使用 read_file 验证修改结果",
            ],
            "code-execution": [
                "使用 terminal 检查环境依赖",
                "编写或修改代码文件",
                "运行测试验证正确性",
                "处理错误并迭代修复",
            ],
            "github-management": [
                "使用 terminal 执行 git 操作",
                "使用 API 或 CLI 查询仓库状态",
                "处理冲突或权限问题",
                "提交并推送变更",
            ],
            "research-analysis": [
                "使用 web_search 收集多个信息源",
                "使用 web_extract 获取详细内容",
                "用 execute_code 进行数据处理和对比",
                "总结发现并结构化输出",
            ],
            "browser-automation": [
                "使用 browser_navigate 打开目标页面",
                "使用 browser_snapshot 获取页面结构",
                "使用 browser_click/type 进行交互",
                "使用 browser_vision 或 console 验证结果",
            ],
            "memory-management": [
                "使用 session_search 定位历史上下文",
                "使用 memory 读取已有记忆",
                "使用 memory action=add/replace 更新记忆",
                "确认记忆持久化成功",
            ],
            "skill-creation": [
                "使用 skill_view 检查已有 skill",
                "分析任务模式提取步骤",
                "使用 skill_manage action=create 创建 skill",
                "测试新 skill 是否可用",
            ],
            "multi-agent-delegation": [
                "将大任务分解为独立子任务",
                "使用 delegate_task 并行分发",
                "等待所有子任务完成",
                "聚合结果并汇报",
            ],
        }

        return step_templates.get(
            pattern.pattern_name,
            [
                f"理解用户{pattern.description}需求",
                "选择合适的工具执行任务",
                "验证执行结果",
                "向用户汇报完成状态",
            ]
        )

    def _best_practice_for(self, pattern_name: str, **kw) -> str:
        practices = {
            "web-scraping": "先搜索再提取，优先用 web_extract 而非 browser（更快更便宜）",
            "file-operation": "先用 read_file 确认内容，再 patch（保留上下文），不用盲目 write_file",
            "code-execution": "先检查依赖再运行，timeout 设充裕，失败后分析日志再重试",
            "github-management": "先 git status/log 了解状态，push 前确认无冲突",
            "research-analysis": "多源交叉验证，不要依赖单一来源，用 execute_code 做数据清洗",
            "browser-automation": "先 browser_navigate 再 browser_snapshot，用 ref ID 定位元素",
            "memory-management": "memory 存关键事实（不是原始数据），session_search 找对话历史",
            "skill-creation": "skill 应包含明确的触发条件、步骤序列和常见陷阱",
            "multi-agent-delegation": "子任务要独立、原子化，通过 context 传递必要信息",
        }
        return practices.get(pattern_name, "遵循最小惊喜原则，每一步都验证结果")

    def save_skill(self, pattern: TaskPattern, skill_md: str, **kw) -> Path:
        """保存 SKILL.md 到磁盘"""
        skill_dir = self.skills_dir / pattern.pattern_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(skill_md, encoding="utf-8")

        logger.info(f"Skill 已生成: {pattern.pattern_name} → {skill_file}")
        return skill_file


# ═══════════════════════════════════════════════════════════
# 记忆合并器
# ═══════════════════════════════════════════════════════════

class MemoryConsolidator:
    """将短期会话记忆合并到长期持久化记忆"""

    def __init__(self, memory_dir: str = None, **kw):
        if memory_dir is None:
            memory_dir = os.path.expanduser("~/.hermes/profiles/meshctx/")
        self.memory_dir = Path(memory_dir)

    def consolidate(self, patterns: List[TaskPattern], **kw) -> int:
        """
        将模式中的关键信息写入记忆
        返回更新的记忆条目数
        """
        count = 0
        memory_file = self.memory_dir / "memory.md"
        if not memory_file.exists():
            return 0

        content = memory_file.read_text(encoding="utf-8")

        for pattern in patterns:
            if not pattern.is_reliable:
                continue

            entry = (f"\n## 🧠 Dreaming: {pattern.pattern_name}\n"
                     f"- 成功率: {pattern.success_rate:.0%} "
                     f"({pattern.success_count}/{pattern.success_count + pattern.failure_count})\n"
                     f"- 推荐工具: {', '.join(pattern.tools_used[:5])}\n"
                     f"- 最后使用: {datetime.fromtimestamp(pattern.last_seen).isoformat()}\n")

            if entry not in content:
                content += entry
                count += 1

        # 防重复：去重旧的 Dreaming 条目
        # 保留最新的3条同类条目
        lines = content.split("\n")
        cleaned = []
        dreaming_sections = []
        in_dreaming = False
        current_section = []

        for line in lines:
            if line.startswith("## 🧠 Dreaming:"):
                if current_section:
                    dreaming_sections.append((current_section[0], "\n".join(current_section)))
                current_section = [line]
                in_dreaming = True
            elif in_dreaming and line.startswith("## "):
                if current_section:
                    dreaming_sections.append((current_section[0], "\n".join(current_section)))
                current_section = []
                in_dreaming = False
                cleaned.append(line)
            elif in_dreaming:
                current_section.append(line)
            else:
                cleaned.append(line)

        if current_section:
            dreaming_sections.append((current_section[0], "\n".join(current_section)))

        # 按模式名去重，保留最新的
        seen = {}
        for header, section in dreaming_sections:
            name = header.replace("## 🧠 Dreaming: ", "").strip()
            seen[name] = section  # 后面的覆盖前面的

        final_content = "\n".join(cleaned + list(seen.values()))

        if final_content != content:
            memory_file.write_text(final_content, encoding="utf-8")
            count = len(dreaming_sections)

        return count


# ═══════════════════════════════════════════════════════════
# DreamingAgent 主插件
# ═══════════════════════════════════════════════════════════

class DreamingPlugin(Plugin):
    """
    Dreaming Agent — 离线记忆整理 & 自动Skill生成

    Cron 触发:
      cron:
        jobs:
          - name: "dreaming"
            schedule: "every 6h"
            action: "dreaming.run"

    或直接调用:
      POST /v1/plugins/dreaming/run
    """

    info = PluginInfo(
        name="dreaming",
        version="1.0.0",
        description="DreamingAgent: 离线记忆整理 + 自动Skill生成 (对标Claude Code Dreaming)",
        author="meshctx",
    )

    def __init__(self, **kw):
        self._scanner: Optional[SessionScanner] = None
        self._extractor: Optional[PatternExtractor] = None
        self._generator: Optional[SkillGenerator] = None
        self._consolidator: Optional[MemoryConsolidator] = None
        self._last_report: Optional[DreamReport] = None

    async def on_load(self):
        self._scanner = SessionScanner()
        self._extractor = PatternExtractor()
        self._generator = SkillGenerator()
        self._consolidator = MemoryConsolidator()

        # 注册 cron 事件监听
        await self.kernel.bus.subscribe("dreaming.run", self._on_dreaming_event)
        await self.kernel.bus.subscribe("dreaming.status", self._on_status_request)

        logger.info("🧠 DreamingAgent 已加载 (每6小时自动运行)")

    async def on_unload(self):
        await self.kernel.bus.unsubscribe("dreaming.run", self._on_dreaming_event)
        logger.info("DreamingAgent 已卸载")

    async def _on_dreaming_event(self, event: Event):
        """Cron 触发入口"""
        logger.info("🌙 Dreaming 周期启动...")
        report = await self.run_dreaming()
        self._last_report = report

        # 发布完成事件
        await self.kernel.bus.publish(Event(
            type="dreaming.complete",
            source="dreaming",
            priority=EventPriority.NORMAL,
            data={
                "sessions_scanned": report.sessions_scanned,
                "patterns_found": report.patterns_found,
                "skills_created": report.skills_created,
                "skills_updated": report.skills_updated,
                "memories_consolidated": report.memories_consolidated,
            },
        ))

    async def _on_status_request(self, event: Event):
        """查询 Dreaming 状态"""
        if self._last_report:
            await self.kernel.bus.publish(Event(
                type="dreaming.status_response",
                source="dreaming",
                priority=EventPriority.LOW,
                data={
                    "last_run": datetime.fromtimestamp(
                        self._last_report.timestamp
                    ).isoformat(),
                    "patterns_found": self._last_report.patterns_found,
                    "skills_total": self._last_report.skills_created + self._last_report.skills_updated,
                },
            ))

    async def run_dreaming(self, since_hours: int = 24) -> DreamReport:
        """
        执行一次完整的 Dreaming 周期

        1. 扫描最近的会话
        2. 提取任务模式
        3. 生成/更新 Skill
        4. 合并记忆
        """
        report = DreamReport(timestamp=time.time())

        try:
            # ── Phase 1: 扫描 ──
            logger.info("📡 Phase 1: 扫描最近会话...")
            sessions = self._scanner.get_recent_sessions(
                since_hours=since_hours, limit=200
            )
            report.sessions_scanned = len(sessions)
            logger.info(f"   扫描了 {len(sessions)} 个会话")

            if not sessions:
                report.errors.append("无符合条件的会话")
                return report

            # ── Phase 2: 提取模式 ──
            logger.info("🔍 Phase 2: 提取任务模式...")
            patterns = self._extractor.extract_patterns(sessions)
            report.patterns_found = len(patterns)
            logger.info(f"   发现 {len(patterns)} 个模式: "
                        f"{[p.pattern_name for p in patterns]}")

            # ── Phase 3: 生成 Skill ──
            logger.info("⚙️ Phase 3: 生成/更新 Skill...")
            for pattern in patterns:
                if not pattern.is_reliable:
                    logger.info(f"   ⏭ 跳过 {pattern.pattern_name} "
                                f"(成功率 {pattern.success_rate:.0%}, "
                                f"次数 {pattern.success_count})")
                    continue

                skill_md = self._generator.generate_skill_md(pattern)
                skill_file = self._generator.save_skill(pattern, skill_md)

                # 判断新建 vs 更新
                if skill_file.stat().st_mtime > time.time() - 10:
                    report.skills_created += 1
                else:
                    report.skills_updated += 1

                logger.info(f"   ✅ {pattern.pattern_name}: "
                            f"成功率 {pattern.success_rate:.0%}")

            # ── Phase 4: 记忆合并 ──
            logger.info("💾 Phase 4: 合并长期记忆...")
            memories = self._consolidator.consolidate(patterns)
            report.memories_consolidated = memories
            logger.info(f"   合并了 {memories} 条记忆")

        except Exception as e:
            msg = f"Dreaming 执行失败: {e}"
            logger.error(msg, exc_info=True)
            report.errors.append(msg)

        # ── 保存报告 ──
        self._save_report(report)
        logger.info(f"🌅 Dreaming 完成: {report.skills_created} 新Skill, "
                    f"{report.memories_consolidated} 条记忆合并")

        return report

    def _save_report(self, report: DreamReport, **kw):
        """持久化 Dreaming 报告"""
        report_dir = Path(os.path.expanduser("~/.meshctx/dreaming/"))
        report_dir.mkdir(parents=True, exist_ok=True)

        report_file = report_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": report.timestamp,
                "sessions_scanned": report.sessions_scanned,
                "patterns_found": report.patterns_found,
                "skills_created": report.skills_created,
                "skills_updated": report.skills_updated,
                "memories_consolidated": report.memories_consolidated,
                "anti_patterns_recorded": report.anti_patterns_recorded,
                "errors": report.errors,
            }, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════
# CLI 工具 — 手动触发
# ═══════════════════════════════════════════════════════════

async def dreaming_cli(since_hours: int = 24):
    """命令行手动触发 Dreaming"""
    agent = DreamingPlugin()
    agent._scanner = SessionScanner()
    agent._extractor = PatternExtractor()
    agent._generator = SkillGenerator()
    agent._consolidator = MemoryConsolidator()

    print("🌙 手动触发 Dreaming...")
    report = await agent.run_dreaming(since_hours=since_hours)

    print(f"\n📊 Dreaming 报告:")
    print(f"   扫描会话: {report.sessions_scanned}")
    print(f"   发现模式: {report.patterns_found}")
    print(f"   新建Skill: {report.skills_created}")
    print(f"   更新Skill: {report.skills_updated}")
    print(f"   记忆合并: {report.memories_consolidated}")
    if report.errors:
        print(f"   ❌ 错误: {report.errors}")

    return report
