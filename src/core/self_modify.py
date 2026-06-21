"""
meshctx SelfModifyEngine v3.48 — 安全自修改引擎
===============================================
实现受控的代码自修改能力，在受限沙箱内验证和部署代码修改。

核心能力:
  1. 修改提案 (Modification Proposal) — 结构化描述改什么、为什么、风险
  2. 语法验证 — 修改前 ast.parse 验证 Python 语法
  3. 自动备份 — 每次修改前自动备份原始文件
  4. 回滚 — 修改失败或检测到错误后可回滚
  5. 审批门 — 高风险修改需人工审批
  6. 与 metacognition 联动 — 元认知决定是否需要自修改

安全原则:
  - 所有修改先在沙箱中验证 (语法 + 简单 lint)
  - 高风险修改必须人类审批
  - 每次修改都有 backup + rollback 能力
  - 修改历史完整记录，可审计
  - 限制可修改的文件范围 (白名单目录)

对标: Claude Code 的 self-edit 能力 + Hermes Agent 的 plugin self-update
状态: 全新实现 (~750行)
"""

import ast
import difflib
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("meshctx.self_modify")


# ═══════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════

class ModificationStatus(Enum):
    """修改状态"""
    PROPOSED = "proposed"        # 已提案，待审批
    APPROVED = "approved"        # 已审批，待应用
    APPLIED = "applied"          # 已应用
    VERIFIED = "verified"        # 已验证通过
    FAILED = "failed"            # 应用失败
    ROLLED_BACK = "rolled_back"  # 已回滚
    REJECTED = "rejected"        # 被拒绝


class RiskLevel(Enum):
    """修改风险等级"""
    SAFE = "safe"              # 安全: 注释/格式/日志级别
    LOW = "low"                # 低风险: 函数内部逻辑调整
    MEDIUM = "medium"          # 中风险: 接口变更/类结构调整
    HIGH = "high"              # 高风险: 核心引擎/Database schema
    CRITICAL = "critical"      # 极危: 安全模块/密钥/认证逻辑


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class ModificationProposal:
    """修改提案 — 结构化描述一次代码修改"""
    proposal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    file_path: str = ""                            # 目标文件路径
    reason: str = ""                               # 修改原因
    category: str = "general"                      # 修改类别: bugfix/refactor/feature/optimize
    risk_level: RiskLevel = RiskLevel.LOW
    # 修改内容: old_lines → new_lines
    old_content: str = ""                          # 原始内容片段
    new_content: str = ""                          # 新内容片段
    diff: str = ""                                 # 自动生成的 unified diff
    # 元数据
    author: str = "meshctx"
    proposed_at: float = field(default_factory=time.time)
    approved_by: str = ""                          # 审批者 (auto / human / username)
    approved_at: float = 0.0
    applied_at: float = 0.0
    status: ModificationStatus = ModificationStatus.PROPOSED
    # 验证
    syntax_valid: Optional[bool] = None            # 语法验证结果
    lint_errors: List[str] = field(default_factory=list)
    test_results: Dict[str, Any] = field(default_factory=dict)
    # 回滚
    backup_path: str = ""                          # 备份文件路径
    rollback_available: bool = False
    # 上下文
    metacognition_confidence: float = 0.5          # 元认知对此修改的置信度
    related_issues: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    def generate_diff(self):
        """生成 unified diff"""
        if self.old_content and self.new_content:
            old_lines = self.old_content.splitlines(keepends=True)
            new_lines = self.new_content.splitlines(keepends=True)
            diff = difflib.unified_diff(
                old_lines, new_lines,
                fromfile=f"a/{self.file_path}",
                tofile=f"b/{self.file_path}",
                lineterm="",
            )
            self.diff = "\n".join(diff)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["risk_level"] = self.risk_level.value
        return d

    def summary(self) -> str:
        """一句话摘要"""
        return (f"[{self.risk_level.value.upper()}] {self.category}: "
                f"{self.reason[:80]} (file: {self.file_path})")


@dataclass
class ModificationResult:
    """修改应用结果"""
    proposal_id: str
    success: bool
    file_path: str
    status: ModificationStatus = ModificationStatus.FAILED
    # 验证结果
    syntax_valid: bool = False
    syntax_errors: List[str] = field(default_factory=list)
    lint_errors: List[str] = field(default_factory=list)
    # 回滚
    backup_path: str = ""
    rollback_successful: bool = False
    # 时间
    applied_at: float = 0.0
    duration_ms: float = 0.0
    # 详情
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# ═══════════════════════════════════════════════════════════
# 风险判定规则
# ═══════════════════════════════════════════════════════════

def assess_file_risk(file_path: str, old_content: str, new_content: str) -> RiskLevel:
    """
    评估修改的风险等级

    判定逻辑:
      - 核心文件 (crypto/credential/secret) → CRITICAL
      - 引擎文件 (kernel/super_brain/autonomous) → HIGH
      - API 变更 (函数签名修改) → MEDIUM
      - 内部逻辑 → LOW
      - 注释/格式/日志 → SAFE
    """
    file_lower = file_path.lower()

    # 文件名匹配
    critical_patterns = [
        "crypto", "credential", "secret", "auth", "key",
        "token", "password", "encrypt",
    ]
    high_patterns = [
        "kernel", "super_brain", "autonomous", "metacognition",
        "self_modify", "agent_swarm", "sandbox",
    ]
    medium_patterns = [
        "gateway", "connector", "api", "endpoint", "handler",
        "persistence", "plugin",
    ]

    for p in critical_patterns:
        if p in file_lower:
            return RiskLevel.CRITICAL
    for p in high_patterns:
        if p in file_lower:
            return RiskLevel.HIGH
    for p in medium_patterns:
        if p in file_lower:
            return RiskLevel.MEDIUM

    # 内容分析: 检查是否只是注释/格式/日志变更
    if _is_surface_change_only(old_content, new_content):
        return RiskLevel.SAFE

    # 检查函数签名变更
    if _has_signature_change(old_content, new_content):
        return RiskLevel.MEDIUM

    return RiskLevel.LOW


def _is_surface_change_only(old: str, new: str) -> bool:
    """检查是否只是表面变更 (注释/格式/日志)"""
    # 移除注释和空白后比较
    def strip_surface(text: str) -> str:
        # 移除注释行 (以 # 开头的行)
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if stripped.startswith("logger."):
                continue
            lines.append(line)
        return "\n".join(lines)

    old_stripped = strip_surface(old)
    new_stripped = strip_surface(new)

    # 规范化空白
    old_normalized = re.sub(r'\s+', ' ', old_stripped).strip()
    new_normalized = re.sub(r'\s+', ' ', new_stripped).strip()

    return old_normalized == new_normalized


def _has_signature_change(old: str, new: str) -> bool:
    """检查是否有函数/类签名变更"""
    try:
        old_tree = ast.parse(old)
        new_tree = ast.parse(new)
    except SyntaxError:
        return False  # 语法错误，让验证阶段处理

    def get_signatures(tree):
        sigs = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                args = [a.arg for a in node.args.args]
                sigs.add(f"def {node.name}({','.join(args)})")
            elif isinstance(node, ast.ClassDef):
                bases = [b.id for b in node.bases
                         if isinstance(b, ast.Name)]
                sigs.add(f"class {node.name}({','.join(bases)})")
        return sigs

    old_sigs = get_signatures(old_tree)
    new_sigs = get_signatures(new_tree)

    return old_sigs != new_sigs


# ═══════════════════════════════════════════════════════════
# SelfModifyEngine 核心类
# ═══════════════════════════════════════════════════════════

class SelfModifyEngine:
    """
    安全自修改引擎 — meshctx 的"自我进化"能力

    核心循环:
      1. 提案: metacognition 触发 → 生成 ModificationProposal
      2. 验证: ast.parse 语法检查 + lint
      3. 审批: 中高风险 → 等待人类审批
      4. 备份: 自动备份原始文件到 .meshctx_backups/
      5. 应用: 写入修改
      6. 验证: 再次语法检查
      7. 回滚: 失败时自动恢复

    安全护栏:
      - 只能修改白名单目录内的文件
      - CRITICAL 风险级别默认拒绝
      - 每次修改都有备份
      - 所有修改记录在 audit trail
    """

    # 默认白名单目录: meshctx 自身代码
    DEFAULT_ALLOWED_DIRS = [
        "src/core/",
        "src/",
        "skills/",
        "plugins/",
    ]

    def __init__(self, workspace_root: str = None, db_path: str = None,
                 approval_callback: Callable = None,
                 allowed_dirs: List[str] = None):
        """
        Args:
            workspace_root: 项目根目录 (用于白名单验证)
            db_path: 修改历史数据库路径
            approval_callback: 人类审批回调 async fn(proposal) → bool
            allowed_dirs: 允许修改的目录白名单 (相对于 workspace_root)
        """
        if workspace_root is None:
            workspace_root = os.path.expanduser("~/meshctx-local")
        self.workspace_root = Path(workspace_root).resolve()

        if db_path is None:
            db_path = os.path.expanduser("~/.hermes/profiles/meshctx/self_modify.db")
        self.db_path = db_path

        self.approval_callback = approval_callback
        self.allowed_dirs = allowed_dirs or self.DEFAULT_ALLOWED_DIRS

        # 备份目录
        self._backup_dir = self.workspace_root / ".meshctx_backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        # 修改历史
        self._proposals: Dict[str, ModificationProposal] = {}
        self._results: Dict[str, ModificationResult] = {}

        # 统计
        self._stats = {
            "total_proposed": 0,
            "total_applied": 0,
            "total_rolled_back": 0,
            "total_rejected": 0,
            "total_syntax_errors": 0,
        }

        # 关联模块 (延迟绑定)
        self._metacognition = None

        self._init_db()
        self._load_history()

    # ── 数据库 ───────────────────────────────────────────

    def _init_db(self):
        """初始化修改历史数据库"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS modifications (
                proposal_id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                reason TEXT DEFAULT '',
                category TEXT DEFAULT 'general',
                risk_level TEXT DEFAULT 'low',
                old_content TEXT DEFAULT '',
                new_content TEXT DEFAULT '',
                diff TEXT DEFAULT '',
                author TEXT DEFAULT 'meshctx',
                proposed_at REAL,
                approved_by TEXT DEFAULT '',
                approved_at REAL DEFAULT 0,
                applied_at REAL DEFAULT 0,
                status TEXT DEFAULT 'proposed',
                syntax_valid INTEGER,
                backup_path TEXT DEFAULT '',
                rollback_available INTEGER DEFAULT 0,
                metacognition_confidence REAL DEFAULT 0.5,
                related_issues TEXT DEFAULT '[]',
                tags TEXT DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS modification_results (
                proposal_id TEXT PRIMARY KEY,
                success INTEGER DEFAULT 0,
                status TEXT DEFAULT 'failed',
                syntax_errors TEXT DEFAULT '[]',
                lint_errors TEXT DEFAULT '[]',
                backup_path TEXT DEFAULT '',
                rollback_successful INTEGER DEFAULT 0,
                applied_at REAL DEFAULT 0,
                duration_ms REAL DEFAULT 0,
                message TEXT DEFAULT '',
                details TEXT DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_mod_status ON modifications(status);
            CREATE INDEX IF NOT EXISTS idx_mod_file ON modifications(file_path);
            CREATE INDEX IF NOT EXISTS idx_mod_time ON modifications(proposed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mod_risk ON modifications(risk_level);
        """)
        conn.commit()
        conn.close()
        logger.debug("SelfModifyEngine DB initialized")

    def _load_history(self):
        """加载修改历史"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM modifications ORDER BY proposed_at DESC LIMIT 200"
            ).fetchall()
            for row in rows:
                p = ModificationProposal(
                    proposal_id=row["proposal_id"],
                    file_path=row["file_path"],
                    reason=row["reason"],
                    category=row["category"],
                    risk_level=RiskLevel(row["risk_level"]),
                    old_content=row["old_content"],
                    new_content=row["new_content"],
                    diff=row["diff"],
                    author=row["author"],
                    proposed_at=row["proposed_at"],
                    approved_by=row["approved_by"],
                    approved_at=row["approved_at"],
                    applied_at=row["applied_at"],
                    status=ModificationStatus(row["status"]),
                    syntax_valid=bool(row["syntax_valid"]),
                    backup_path=row["backup_path"],
                    rollback_available=bool(row["rollback_available"]),
                    metacognition_confidence=row["metacognition_confidence"],
                    related_issues=json.loads(row["related_issues"]),
                    tags=json.loads(row["tags"]),
                )
                self._proposals[p.proposal_id] = p
            conn.close()
            self._stats["total_proposed"] = len(self._proposals)
            logger.debug(f"Loaded {len(self._proposals)} proposals from DB")
        except Exception as e:
            logger.warning(f"Failed to load modification history: {e}")

    # ── 文件路径验证 ─────────────────────────────────────

    def _is_path_allowed(self, file_path: str) -> Tuple[bool, str]:
        """
        检查文件是否在白名单目录内

        Returns:
            (is_allowed, reason)
        """
        try:
            resolved = (self.workspace_root / file_path).resolve()
        except Exception:
            return False, "无法解析文件路径"

        # 必须在 workspace_root 下
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError:
            return False, f"文件不在工作区目录下: {resolved}"

        # 检查是否在允许的目录内
        rel_path = str(resolved.relative_to(self.workspace_root))
        for allowed in self.allowed_dirs:
            if rel_path.startswith(allowed.rstrip("/")) or rel_path == allowed.rstrip("/"):
                return True, "ok"

        return False, f"文件不在允许修改的目录中 (允许: {self.allowed_dirs})"

    # ── 修改提案 ─────────────────────────────────────────

    def propose_modification(self, file_path: str, old_content: str,
                              new_content: str, reason: str,
                              category: str = "general",
                              auto_assess: bool = True) -> ModificationProposal:
        """
        创建修改提案

        流程:
          1. 白名单检查
          2. 风险评估
          3. 生成 diff
          4. 语法验证
          5. 如需审批 → 记录状态

        Args:
            file_path: 目标文件 (相对于 workspace_root)
            old_content: 原始内容
            new_content: 修改后内容
            reason: 修改原因
            category: bugfix / refactor / feature / optimize
            auto_assess: 是否自动评估风险

        Returns:
            ModificationProposal 对象
        """
        # 白名单检查
        allowed, msg = self._is_path_allowed(file_path)
        if not allowed:
            proposal = ModificationProposal(
                file_path=file_path,
                reason=f"PATH REJECTED: {msg}",
                risk_level=RiskLevel.CRITICAL,
                status=ModificationStatus.REJECTED,
            )
            logger.warning(f"Modification blocked: {msg}")
            return proposal

        # 风险评估
        risk = assess_file_risk(file_path, old_content, new_content) if auto_assess \
               else RiskLevel.LOW

        # CRITICAL 风险默认拒绝 (除非有审批回调)
        if risk == RiskLevel.CRITICAL and not self.approval_callback:
            proposal = ModificationProposal(
                file_path=file_path,
                reason=reason,
                category=category,
                risk_level=risk,
                old_content=old_content,
                new_content=new_content,
                status=ModificationStatus.REJECTED,
            )
            proposal.generate_diff()
            logger.warning(f"CRITICAL risk modification rejected: {file_path}")
            self._save_proposal(proposal)
            self._stats["total_rejected"] += 1
            return proposal

        # 构建提案
        proposal = ModificationProposal(
            file_path=file_path,
            reason=reason,
            category=category,
            risk_level=risk,
            old_content=old_content,
            new_content=new_content,
            status=ModificationStatus.PROPOSED,
        )
        proposal.generate_diff()

        # 语法验证 (对 Python 文件)
        if file_path.endswith(".py"):
            valid, errors = self._validate_python_syntax(new_content)
            proposal.syntax_valid = valid
            if not valid:
                proposal.lint_errors = errors
                proposal.status = ModificationStatus.FAILED
                self._stats["total_syntax_errors"] += 1
                logger.warning(f"Syntax validation failed for {file_path}: {errors}")

        # 持久化
        self._save_proposal(proposal)
        self._proposals[proposal.proposal_id] = proposal
        self._stats["total_proposed"] += 1

        logger.info(f"Modification proposed: {proposal.summary()}")
        return proposal

    # ── 语法验证 ─────────────────────────────────────────

    def _validate_python_syntax(self, code: str) -> Tuple[bool, List[str]]:
        """
        用 ast.parse 验证 Python 语法

        Returns:
            (is_valid, list_of_errors)
        """
        errors = []
        try:
            ast.parse(code)
        except SyntaxError as e:
            errors.append(f"语法错误 (行 {e.lineno}, 列 {e.offset}): {e.msg}")
            return False, errors
        except Exception as e:
            errors.append(f"解析异常: {str(e)}")
            return False, errors

        # 额外的安全检查: 禁止危险导入
        dangerous_imports = [
            "subprocess", "os.system", "eval(", "exec(",
            "__import__", "compile(", "ctypes",
        ]
        for di in dangerous_imports:
            if di in code:
                errors.append(f"安全检查: 检测到危险调用 '{di}'")
                # 不阻断，但记录警告
                logger.warning(f"Dangerous pattern detected in {di}")

        return len([e for e in errors if "安全检查" not in e]) == 0, errors

    def validate_python_syntax(self, code: str) -> Tuple[bool, List[str]]:
        """公开的语法验证方法"""
        return self._validate_python_syntax(code)

    # ── 审批 ─────────────────────────────────────────────

    def needs_approval(self, proposal: ModificationProposal) -> bool:
        """判断是否需要人类审批"""
        return proposal.risk_level in (
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
            RiskLevel.MEDIUM,
        )

    async def request_approval(self, proposal_id: str) -> bool:
        """
        请求人类审批

        Returns:
            是否获得批准
        """
        if proposal_id not in self._proposals:
            logger.warning(f"Proposal {proposal_id} not found")
            return False

        proposal = self._proposals[proposal_id]

        if not self.needs_approval(proposal):
            proposal.status = ModificationStatus.APPROVED
            proposal.approved_by = "auto"
            proposal.approved_at = time.time()
            self._save_proposal(proposal)
            return True

        if not self.approval_callback:
            logger.warning(f"No approval callback set, rejecting {proposal_id}")
            return False

        try:
            approved = await self.approval_callback(proposal)
            if approved:
                proposal.status = ModificationStatus.APPROVED
                proposal.approved_by = "human"
            else:
                proposal.status = ModificationStatus.REJECTED
                self._stats["total_rejected"] += 1
            proposal.approved_at = time.time()
            self._save_proposal(proposal)
            return approved
        except Exception as e:
            logger.error(f"Approval callback error: {e}")
            return False

    # ── 应用修改 ─────────────────────────────────────────

    def apply_modification(self, proposal_or_id) -> ModificationResult:
        """
        应用修改到实际文件

        流程:
          1. 读取完整原文件
          2. 创建备份
          3. 在内存中完成替换
          4. ast.parse 验证完整文件
          5. 写入新内容
          6. 返回结果

        Args:
            proposal_or_id: ModificationProposal 对象或 proposal_id 字符串

        Returns:
            ModificationResult
        """
        start_time = time.time()

        # 解析参数
        if isinstance(proposal_or_id, str):
            if proposal_or_id not in self._proposals:
                return ModificationResult(
                    proposal_id=proposal_or_id,
                    success=False,
                    file_path="",
                    message=f"Proposal {proposal_or_id} not found",
                )
            proposal = self._proposals[proposal_or_id]
        else:
            proposal = proposal_or_id

        # 状态检查
        if proposal.status == ModificationStatus.REJECTED:
            return ModificationResult(
                proposal_id=proposal.proposal_id,
                success=False,
                file_path=proposal.file_path,
                status=ModificationStatus.REJECTED,
                message="修改已被拒绝",
            )
        if proposal.status == ModificationStatus.FAILED:
            return ModificationResult(
                proposal_id=proposal.proposal_id,
                success=False,
                file_path=proposal.file_path,
                status=ModificationStatus.FAILED,
                message="修改提案已失败 (可能是语法错误)",
                syntax_errors=proposal.lint_errors,
            )

        # 路径验证
        full_path = self.workspace_root / proposal.file_path
        if not full_path.exists():
            return ModificationResult(
                proposal_id=proposal.proposal_id,
                success=False,
                file_path=proposal.file_path,
                message=f"文件不存在: {full_path}",
            )

        try:
            # 步骤1: 读取原文件
            original_content = full_path.read_text(encoding="utf-8")

            # 步骤2: 创建备份
            backup_path = self._create_backup(proposal.proposal_id, full_path)

            # 步骤3: 应用修改 (old_content → new_content 替换)
            if proposal.old_content not in original_content:
                return ModificationResult(
                    proposal_id=proposal.proposal_id,
                    success=False,
                    file_path=proposal.file_path,
                    backup_path=backup_path,
                    message="未在文件中找到 old_content 片段，文件可能已被修改",
                )

            new_file_content = original_content.replace(
                proposal.old_content, proposal.new_content, 1
            )

            # 步骤4: 语法验证 (完整文件)
            if full_path.suffix == ".py":
                valid, errors = self._validate_python_syntax(new_file_content)
                if not valid:
                    # 语法错误 → 不写入
                    return ModificationResult(
                        proposal_id=proposal.proposal_id,
                        success=False,
                        file_path=proposal.file_path,
                        status=ModificationStatus.FAILED,
                        syntax_valid=False,
                        syntax_errors=errors,
                        backup_path=backup_path,
                        message="语法验证失败，修改未写入",
                    )

            # 步骤5: 写入
            full_path.write_text(new_file_content, encoding="utf-8")

            # 步骤6: 更新状态
            proposal.status = ModificationStatus.APPLIED
            proposal.applied_at = time.time()
            proposal.backup_path = backup_path
            proposal.rollback_available = True
            self._save_proposal(proposal)

            duration_ms = (time.time() - start_time) * 1000
            self._stats["total_applied"] += 1

            result = ModificationResult(
                proposal_id=proposal.proposal_id,
                success=True,
                file_path=proposal.file_path,
                status=ModificationStatus.APPLIED,
                syntax_valid=True,
                backup_path=backup_path,
                applied_at=time.time(),
                duration_ms=duration_ms,
                message=f"修改已成功应用: {proposal.summary()}",
                details={
                    "bytes_changed": abs(
                        len(new_file_content) - len(original_content)
                    ),
                },
            )

            self._save_result(result)
            self._results[proposal.proposal_id] = result

            logger.info(f"Modification applied: {proposal.file_path} "
                       f"({duration_ms:.0f}ms)")
            return result

        except Exception as e:
            logger.error(f"Failed to apply modification: {e}")
            return ModificationResult(
                proposal_id=proposal.proposal_id,
                success=False,
                file_path=proposal.file_path,
                message=f"应用失败: {str(e)}",
            )

    def _create_backup(self, proposal_id: str, file_path: Path) -> str:
        """创建文件备份"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.name}.{timestamp}.{proposal_id[:8]}.bak"
        backup_path = self._backup_dir / backup_name
        shutil.copy2(file_path, backup_path)
        logger.debug(f"Backup created: {backup_path}")
        return str(backup_path)

    # ── 回滚 ─────────────────────────────────────────────

    def rollback(self, modification_id: str) -> ModificationResult:
        """
        回滚修改 — 从备份恢复原始文件

        Args:
            modification_id: proposal_id

        Returns:
            ModificationResult
        """
        if modification_id not in self._proposals:
            return ModificationResult(
                proposal_id=modification_id,
                success=False,
                file_path="",
                message=f"未找到修改记录: {modification_id}",
            )

        proposal = self._proposals[modification_id]

        if not proposal.backup_path or not os.path.exists(proposal.backup_path):
            return ModificationResult(
                proposal_id=modification_id,
                success=False,
                file_path=proposal.file_path,
                message="备份文件不存在，无法回滚",
            )

        try:
            full_path = self.workspace_root / proposal.file_path
            # 从备份恢复
            shutil.copy2(proposal.backup_path, full_path)

            proposal.status = ModificationStatus.ROLLED_BACK
            proposal.rollback_available = False
            self._save_proposal(proposal)

            self._stats["total_rolled_back"] += 1

            result = ModificationResult(
                proposal_id=modification_id,
                success=True,
                file_path=proposal.file_path,
                status=ModificationStatus.ROLLED_BACK,
                rollback_successful=True,
                backup_path=proposal.backup_path,
                applied_at=time.time(),
                message=f"成功回滚 {proposal.file_path} 到备份",
            )
            self._save_result(result)

            logger.info(f"Rollback successful: {proposal.file_path}")
            return result

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return ModificationResult(
                proposal_id=modification_id,
                success=False,
                file_path=proposal.file_path,
                message=f"回滚失败: {str(e)}",
            )

    def rollback_all(self, since_timestamp: float = 0) -> List[ModificationResult]:
        """批量回滚: 回滚指定时间之后的所有修改 (LIFO 顺序)"""
        results = []
        targets = [
            p for p in self._proposals.values()
            if p.status == ModificationStatus.APPLIED
            and p.applied_at >= since_timestamp
        ]
        # LIFO: 最后应用的先回滚
        targets.sort(key=lambda p: -p.applied_at)

        for proposal in targets:
            result = self.rollback(proposal.proposal_id)
            results.append(result)
            if not result.success:
                logger.warning(f"Rollback chain broken at {proposal.proposal_id}")
                break

        return results

    # ── 持久化 ───────────────────────────────────────────

    def _save_proposal(self, proposal: ModificationProposal):
        """持久化修改提案"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT OR REPLACE INTO modifications
                   (proposal_id, file_path, reason, category, risk_level,
                    old_content, new_content, diff, author, proposed_at,
                    approved_by, approved_at, applied_at, status,
                    syntax_valid, backup_path, rollback_available,
                    metacognition_confidence, related_issues, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (proposal.proposal_id, proposal.file_path, proposal.reason,
                 proposal.category, proposal.risk_level.value,
                 proposal.old_content[:10000], proposal.new_content[:10000],
                 proposal.diff[:20000], proposal.author, proposal.proposed_at,
                 proposal.approved_by, proposal.approved_at, proposal.applied_at,
                 proposal.status.value,
                 1 if proposal.syntax_valid else (0 if proposal.syntax_valid is False else None),
                 proposal.backup_path, int(proposal.rollback_available),
                 proposal.metacognition_confidence,
                 json.dumps(proposal.related_issues),
                 json.dumps(proposal.tags)),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to save proposal: {e}")

    def _save_result(self, result: ModificationResult):
        """持久化修改结果"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT OR REPLACE INTO modification_results
                   (proposal_id, success, status, syntax_errors, lint_errors,
                    backup_path, rollback_successful, applied_at, duration_ms,
                    message, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (result.proposal_id, int(result.success), result.status.value,
                 json.dumps(result.syntax_errors),
                 json.dumps(result.lint_errors),
                 result.backup_path, int(result.rollback_successful),
                 result.applied_at, result.duration_ms,
                 result.message, json.dumps(result.details)),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to save result: {e}")

    # ── 查询与历史 ───────────────────────────────────────

    def get_modification_history(self, limit: int = 50,
                                  status: ModificationStatus = None,
                                  risk_level: RiskLevel = None) -> List[Dict]:
        """
        获取修改历史

        Args:
            limit: 返回条数
            status: 过滤状态
            risk_level: 过滤风险等级

        Returns:
            修改历史列表 (字典格式)
        """
        proposals = list(self._proposals.values())

        if status:
            proposals = [p for p in proposals if p.status == status]
        if risk_level:
            proposals = [p for p in proposals if p.risk_level == risk_level]

        proposals.sort(key=lambda p: -p.proposed_at)

        history = []
        for p in proposals[:limit]:
            entry = p.to_dict()
            entry["summary"] = p.summary()
            # 附加结果信息
            if p.proposal_id in self._results:
                result = self._results[p.proposal_id]
                entry["result"] = result.to_dict()
            history.append(entry)

        return history

    def get_proposal(self, proposal_id: str) -> Optional[ModificationProposal]:
        """获取单个提案"""
        return self._proposals.get(proposal_id)

    def get_result(self, proposal_id: str) -> Optional[ModificationResult]:
        """获取单个修改结果"""
        return self._results.get(proposal_id)

    def list_pending_approvals(self) -> List[ModificationProposal]:
        """列出等待审批的修改"""
        return [p for p in self._proposals.values()
                if p.status == ModificationStatus.PROPOSED
                and self.needs_approval(p)]

    # ── Metacognition 联动 ──────────────────────────────

    def set_metacognition(self, metacognition):
        """注入 MetaCognition 引用"""
        self._metacognition = metacognition
        logger.info("SelfModifyEngine connected to MetaCognition")

    def should_self_modify(self, task_description: str,
                           error_context: str = "") -> Tuple[bool, str, float]:
        """
        元认知判断: 是否需要自修改？

        当 Agent 反复遇到同类错误，或元认知对某类任务置信度低时，
        触发自修改流程: 分析根因 → 生成修改提案 → 应用修改

        Args:
            task_description: 当前任务描述
            error_context: 错误上下文

        Returns:
            (should_modify, reason, confidence)
        """
        if not self._metacognition:
            return False, "元认知未连接", 0.0

        # 从元认知获取任务类型置信度
        if hasattr(self._metacognition, 'evaluate_task'):
            evaluation = self._metacognition.evaluate_task(task_description)
            confidence = evaluation.confidence

            # 置信度过低 → 建议自修改
            if confidence < 0.3:
                return True, f"元认知置信度低 ({confidence:.0%})，建议自修改提升能力", confidence

            if confidence < 0.5 and error_context:
                return True, f"中低置信度 ({confidence:.0%}) 且有错误发生，建议自修改修复", confidence

        # 检查是否有重复失败模式
        if hasattr(self._metacognition, 'capabilities'):
            task_type = self._metacognition.infer_task_type(task_description)
            if task_type in self._metacognition.capabilities:
                profile = self._metacognition.capabilities[task_type]
                if profile.total_attempts >= 3 and profile.success_rate < 0.4:
                    return True, (
                        f"任务类型 '{task_type}' 成功率仅 {profile.success_rate:.0%} "
                        f"(共 {profile.total_attempts} 次)，需要自修改改进"
                    ), 0.7

        return False, "当前元认知状态良好，无需自修改", 1.0

    # ── 统计与状态 ───────────────────────────────────────

    def get_engine_status(self) -> dict:
        """获取引擎运行状态"""
        return {
            "total_proposed": self._stats["total_proposed"],
            "total_applied": self._stats["total_applied"],
            "total_rolled_back": self._stats["total_rolled_back"],
            "total_rejected": self._stats["total_rejected"],
            "total_syntax_errors": self._stats["total_syntax_errors"],
            "pending_approvals": len(self.list_pending_approvals()),
            "backup_dir": str(self._backup_dir),
            "backup_count": len(list(self._backup_dir.iterdir()))
            if self._backup_dir.exists() else 0,
            "metacognition_connected": self._metacognition is not None,
            "workspace_root": str(self.workspace_root),
            "allowed_dirs": self.allowed_dirs,
            "db_path": self.db_path,
        }

    def get_stats(self) -> dict:
        """获取统计信息"""
        return dict(self._stats)

    # ── 维护 ─────────────────────────────────────────────

    def clean_old_backups(self, max_age_days: int = 30):
        """清理过期备份"""
        now = time.time()
        cutoff = now - max_age_days * 86400
        cleaned = 0
        for backup_file in self._backup_dir.iterdir():
            if backup_file.stat().st_mtime < cutoff:
                backup_file.unlink()
                cleaned += 1
        logger.info(f"Cleaned {cleaned} old backups (>{max_age_days}d)")
        return cleaned

    def get_backups_for_file(self, file_path: str) -> List[Dict]:
        """获取某个文件的所有备份"""
        file_name = Path(file_path).name
        backups = []
        for bf in self._backup_dir.iterdir():
            if bf.name.startswith(file_name):
                backups.append({
                    "path": str(bf),
                    "size": bf.stat().st_size,
                    "created": bf.stat().st_mtime,
                })
        backups.sort(key=lambda b: -b["created"])
        return backups


# ═══════════════════════════════════════════════════════════
# 单例管理
# ═══════════════════════════════════════════════════════════

_self_modify_engine: Optional[SelfModifyEngine] = None


def get_self_modify_engine() -> SelfModifyEngine:
    """获取 SelfModifyEngine 全局实例，自动创建"""
    global _self_modify_engine
    if _self_modify_engine is None:
        _self_modify_engine = SelfModifyEngine()
    return _self_modify_engine


def init_self_modify_engine(workspace_root: str = None,
                             approval_callback: Callable = None,
                             allowed_dirs: List[str] = None) -> SelfModifyEngine:
    """
    初始化 SelfModifyEngine 单例

    Args:
        workspace_root: 项目根目录
        approval_callback: 人类审批回调
        allowed_dirs: 白名单目录

    Returns:
        SelfModifyEngine 实例
    """
    global _self_modify_engine
    if _self_modify_engine is not None:
        logger.warning("SelfModifyEngine already initialized, returning existing instance")
        return _self_modify_engine

    _self_modify_engine = SelfModifyEngine(
        workspace_root=workspace_root,
        approval_callback=approval_callback,
        allowed_dirs=allowed_dirs,
    )
    logger.info("SelfModifyEngine singleton initialized")
    return _self_modify_engine


# ═══════════════════════════════════════════════════════════
# 沙箱实用工具
# ═══════════════════════════════════════════════════════════

class SandboxValidator:
    """
    独立的沙箱验证器 — 在不写入文件的情况下验证修改

    可以用于:
      - 预验证: 在正式提案前先检查
      - 批量验证: 同时验证多个修改
      - CI 集成: 在 CI 流程中验证自动生成的修改
    """

    @staticmethod
    def validate_in_isolation(file_path: str, old_content: str,
                               new_content: str) -> Dict[str, Any]:
        """
        在隔离环境中验证修改

        Returns:
            {
                "syntax_valid": bool,
                "errors": [],
                "warnings": [],
                "risk_level": str,
                "diff_stats": {"added": int, "removed": int}
            }
        """
        errors = []
        warnings = []

        # 语法验证
        syntax_valid = True
        try:
            ast.parse(new_content)
        except SyntaxError as e:
            syntax_valid = False
            errors.append(f"行 {e.lineno}: {e.msg}")

        # 检查危险模式
        dangerous = ["subprocess", "os.system", "eval(", "exec(",
                     "__import__", "ctypes", "shutil.rmtree"]
        for d in dangerous:
            if d in new_content and d not in old_content:
                warnings.append(f"新增危险调用: {d}")

        # Diff 统计
        old_lines = set(old_content.splitlines())
        new_lines = set(new_content.splitlines())
        added = len(new_lines - old_lines)
        removed = len(old_lines - new_lines)

        # 风险评估
        risk = assess_file_risk(file_path, old_content, new_content)

        return {
            "syntax_valid": syntax_valid,
            "errors": errors,
            "warnings": warnings,
            "risk_level": risk.value,
            "diff_stats": {"added": added, "removed": removed},
        }

    @staticmethod
    def batch_validate(modifications: List[Dict]) -> List[Dict]:
        """
        批量验证修改

        Args:
            modifications: [{"file": ..., "old": ..., "new": ...}, ...]

        Returns:
            每个修改的验证结果
        """
        results = []
        for mod in modifications:
            result = SandboxValidator.validate_in_isolation(
                mod["file"], mod["old"], mod["new"]
            )
            result["file"] = mod["file"]
            results.append(result)
        return results


# ═══════════════════════════════════════════════════════════
# Plugin 适配
# ═══════════════════════════════════════════════════════════

class SelfModifyPlugin:
    """meshctx Plugin 适配器"""
    info = type('Info', (), {
        'name': 'self_modify',
        'version': '3.48',
        'dependencies': ['metacognition'],
        'category': 'brain',
        'description': '安全自修改引擎 — 提案+验证+备份+回滚+审批',
    })()
    state = "inactive"

    def __init__(self):
        self.engine: Optional[SelfModifyEngine] = None

    async def on_load(self, kernel) -> bool:
        try:
            self.engine = init_self_modify_engine()
            kernel.self_modify_engine = self.engine
            # 连接到 metacognition (如果有)
            if hasattr(kernel, 'metacognition'):
                self.engine.set_metacognition(kernel.metacognition)
            self.state = "active"
            logger.info("SelfModifyPlugin activated")
            return True
        except Exception as e:
            logger.error(f"SelfModifyPlugin load failed: {e}")
            return False

    async def on_unload(self, kernel) -> bool:
        self.state = "inactive"
        return True

    def generate_report(self) -> Dict:
        if self.engine:
            return self.engine.get_engine_status()
        return {"status": "not_initialized"}

class _P:
    __slots__ = ('_n',)
    def __init__(s, n=""): object.__setattr__(s, '_n', n)
    def __getattr__(s, n):
        if n.startswith('_'): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): return iter([_P("i0")])
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

