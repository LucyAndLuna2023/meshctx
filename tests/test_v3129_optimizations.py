# -*- coding: utf-8 -*-
"""v3.129.0 优化回归保护 (2026-09-09 优化批)

覆盖三项优化的防回归:
  ① 裸 open() 补 encoding="utf-8" — AST 全量校验 src/ 无缺编码的文本模式 open()
  ② src/core/_known 符号映射修复 — 无重复键 / 真实模块符号不误降级 stub
  ③ 版本一致性 — src.__version__ == src.core.__version__ == 3.129.0
"""
import ast
import importlib
import re
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

BIN_FLAGS = {"rb", "br", "wb", "bw", "ab", "ba", "xb", "bx"}
# 属性型 .open(): 仅对"确定接受 encoding 形参"的模块 API 强制;
# 其余 (os.open/webbrowser.open/sftp.open/PIL.Image.open/zipfile...) 签名各异,
# 过度注入 encoding 反而 TypeError (运行期 + scripts/opt_audit_attr_open.py 兜底)
ENCODING_CAPABLE_OPEN_ROOTS = {"gzip", "bz2", "lzma", "tarfile", "codecs",
                               "io", "tokenize", "pathlib"}


# ── ① encoding 补齐回归 ──────────────────────────────────────

def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _bare_text_opens(py: Path):
    """返回文件中缺 encoding 的文本模式 open() 调用行号列表。"""
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []  # 语法/编码问题由编译期其他测试覆盖
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name):
            if f.id != "open":
                continue
        elif isinstance(f, ast.Attribute) and f.attr == "open":
            if _dotted(f).split(".")[0] not in ENCODING_CAPABLE_OPEN_ROOTS:
                continue
        else:
            continue
        if any(kw.arg == "encoding" for kw in node.keywords) or len(node.args) >= 4:
            continue
        mode = "r"
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            mode = node.args[1].value or "r"
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value or "r"
        if "b" in mode or mode in BIN_FLAGS:
            continue
        bad.append(node.lineno)
    return bad


def test_no_bare_text_mode_open_in_src():
    """src/ 全树禁止缺 encoding 的文本模式 open() (中文 Windows GBK 默认编码防护)。"""
    offenders = {}
    for py in SRC_DIR.rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        lines = _bare_text_opens(py)
        if lines:
            offenders[str(py.relative_to(SRC_DIR.parent))] = lines[:5]
    assert not offenders, f"缺 encoding 的 open(): {offenders}"


# ── ② _known 符号映射回归 ────────────────────────────────────

def _parse_known_literal():
    src = (SRC_DIR / "core" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r"_known = \{(.*?)\n\}\n", src, re.S)
    assert m, "_known 字面量未找到"
    keys = re.findall(r"'([a-z0-9_]+)':\s*\[", m.group(1))
    return keys


def test_known_map_no_duplicate_keys():
    """_known 字典字面量禁止重复键 (后者静默覆盖前者导致符号误降级 stub)。"""
    keys = _parse_known_literal()
    dups = sorted({k for k in keys if keys.count(k) > 1})
    assert not dups, f"_known 重复键: {dups}"


CURATED_EXISTING_MODULES = [
    # 本批修复涉及的模块 + 代表性真实实现模块
    ("autonomous_engine", ["AutonomousEngine", "EngineState", "TaskQueue",
                           "HeartbeatMonitor", "AutoHealer", "TaskPriority",
                           "Severity", "ScheduledTask", "get_autonomous_engine"]),
    ("realtime_push", ["RealtimePush", "ConnectionManager",
                       "create_realtime_router", "get_realtime"]),
    ("agent_swarm_v2", ["AgentSwarmV2", "get_agent_swarm_v2",
                        "reset_agent_swarm_v2", "TaskMarket", "ConsensusEngine"]),
    ("brain", ["SuperBrain", "get_super_brain"]),
    ("jepa_world_model", ["JEPAWorldModel", "get_jepa_world_model"]),
]


@pytest.mark.parametrize("mod_name,symbols", CURATED_EXISTING_MODULES)
def test_known_symbols_exist_in_real_modules(mod_name, symbols):
    """真实存在的模块, 其 _known 声明符号必须真实存在 (防假符号→误降级 stub)。"""
    mod = importlib.import_module(f"src.core.{mod_name}")
    missing = [s for s in symbols if not hasattr(mod, s)]
    assert not missing, f"src.core.{mod_name} 缺符号: {missing}"


@pytest.mark.parametrize("attr", ["AutonomousEngine", "RealtimePush", "TaskQueue"])
def test_package_getattr_resolves_real_class(attr):
    """from src.core import X 必须拿到真实类, 而非 _StubProxy
    (回归: autonomous_engine 重复键曾使 AutonomousEngine 误降级 stub)。"""
    import src.core as core
    resolved = getattr(core, attr)
    assert resolved is not core._stub, f"{attr} 被误降级为 stub"
    assert isinstance(resolved, type), f"{attr} 应为类, 实际: {resolved!r}"


# ── ③ 版本一致性 ─────────────────────────────────────────────

def test_version_consistency_3129():
    """版本一致性: src ≡ src.core ≡ pyproject (对账式, 不钉死具体版本号)。"""
    import re
    from pathlib import Path
    import src
    import src.core as core
    assert src.__version__ == core.__version__
    py = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', py, re.M)
    assert m, "pyproject.toml 缺 version 字段"
    assert src.__version__ == m.group(1), f"src.__version__({src.__version__}) != pyproject({m.group(1)})"
