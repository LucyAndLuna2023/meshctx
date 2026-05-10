"""
meshctx SOUL.md — 系统提示自定义 (对标 Hermes SOUL.md)

用法: 在 ~/.meshctx/SOUL.md 中写入自定义提示
meshctx 每次启动自动加载，注入到系统提示最前面
"""
import os
from pathlib import Path

SOUL_PATH = Path.home() / ".meshctx" / "SOUL.md"

def load_soul() -> str:
    """加载 SOUL.md 内容"""
    if SOUL_PATH.exists():
        content = SOUL_PATH.read_text(encoding="utf-8").strip()
        if content:
            return content
    return ""

def save_soul(content: str):
    """保存 SOUL.md"""
    SOUL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOUL_PATH.write_text(content, encoding="utf-8")

def has_soul() -> bool:
    return SOUL_PATH.exists() and bool(SOUL_PATH.read_text().strip())

def get_soul_prompt() -> str:
    """获取完整的系统提示(SOUL.md + 默认提示)"""
    soul = load_soul()
    if soul:
        return f"[SOUL.md 自定义指令]\n{soul}\n[/SOUL.md]\n\n"
    return ""
