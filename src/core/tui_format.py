"""
meshctx TUI Format Rules v1.0 — Independent Formatting Fragment System

Design (inspired by Late-CLI's format rule isolation):
  - Format rules are INDEPENDENT fragments, injected only into final output
  - Each fragment is hash-stable → cache-friendly
  - Rules loaded from .meshctx/formats/ directory
  - Support: markdown, diff, terminal, json, table, codeblock

Fragment format:
  Each .format.yaml file defines ONE output format rule:
    name: "diff"
    trigger: "when showing code changes"
    rules:
      - "Use unified diff format"
      - "Include +/- line prefixes"
      - "Show 3 lines of context"

Usage:
  engine = TUIFormatEngine()
  rules = engine.get_rules_for("diff")  # → ["Rule 1", "Rule 2", ...]
  prompt_fragment = engine.format_for("diff")  # → formatted text ready for injection
"""

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import logging

logger = logging.getLogger("meshctx.tui_format")


# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

DEFAULT_FORMATS_DIR = Path.home() / ".meshctx" / "formats"
FORMAT_EXT = ".format.yaml"


# ═══════════════════════════════════════════════════════════
# Built-in Format Rules
# ═══════════════════════════════════════════════════════════

BUILTIN_FORMATS = {
    "diff": {
        "name": "diff",
        "description": "Code diff output format",
        "triggers": ["diff", "patch", "change", "delta", "compare"],
        "rules": [
            "Use unified diff format with +/- prefixes",
            "Show 3 lines of context around each change",
            "Include file path as diff header",
            "Group related changes by file",
        ],
    },
    "markdown": {
        "name": "markdown",
        "description": "Markdown document output format",
        "triggers": ["markdown", "readme", "documentation", "docs"],
        "rules": [
            "Use proper markdown headings (##, ###)",
            "Code blocks must specify language: ```python",
            "Lists use - prefix, not *",
            "Tables align columns",
            "Links use [text](url) format",
        ],
    },
    "terminal": {
        "name": "terminal",
        "description": "Terminal command output format",
        "triggers": ["terminal", "shell", "command", "bash", "zsh"],
        "rules": [
            "Prefix commands with $",
            "Show exit code when non-zero: [exit: 1]",
            "Truncate output > 200 lines with [...truncated]",
            "Use ```bash code blocks for multi-line commands",
            "Warn about destructive commands (# DANGER: ...)",
        ],
    },
    "json": {
        "name": "json",
        "description": "JSON output format",
        "triggers": ["json", "api", "response", "data"],
        "rules": [
            "Use 2-space indentation",
            "Never include trailing commas",
            "Use double quotes for keys and strings",
            "Pretty-print with json.dumps(indent=2)",
        ],
    },
    "table": {
        "name": "table",
        "description": "Tabular data output format",
        "triggers": ["table", "tabular", "spreadsheet", "csv", "list"],
        "rules": [
            "Use markdown table format with aligned columns",
            "Header row separated by --- dividers",
            "Right-align numbers, left-align text",
            "Keep tables under 80 chars wide",
            "Use ... for truncated cells",
        ],
    },
    "codeblock": {
        "name": "codeblock",
        "description": "Code block output format",
        "triggers": ["code", "source", "function", "class", "module"],
        "rules": [
            "Always specify language in fenced code blocks",
            "Use ```language not indented code",
            "Keep blocks under 100 lines",
            "Use # ... for omitted sections",
            "Prefix file path before block: // path/to/file.py",
        ],
    },
}


# ═══════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════

class FormatRule:
    """A single formatting rule fragment."""
    def __init__(self, name: str = "", description: str = "",
                 triggers: Optional[List[str]] = None,
                 rules: Optional[List[str]] = None):
        self.name = name
        self.description = description
        self.triggers = triggers or []
        self.rules = rules or []
        self._hash: str = ""
        self._formatted: str = ""
    
    @property
    def content_hash(self) -> str:
        """Hash-stable identifier for this rule set."""
        if not self._hash:
            self._hash = hashlib.sha256(
                "\n".join(self.rules).encode()
            ).hexdigest()[:12]
        return self._hash
    
    @property
    def formatted(self) -> str:
        """Render rules as injectable text fragment."""
        if not self._formatted:
            lines = [f"## {self.name.upper()} FORMAT RULES"]
            for i, rule in enumerate(self.rules, 1):
                lines.append(f"  {i}. {rule}")
            self._formatted = "\n".join(lines)
        return self._formatted
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "triggers": self.triggers,
            "rules": self.rules,
            "hash": self.content_hash,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "FormatRule":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            triggers=data.get("triggers", []),
            rules=data.get("rules", []),
        )


# ═══════════════════════════════════════════════════════════
# TUI Format Engine
# ═══════════════════════════════════════════════════════════

class TUIFormatEngine:
    """
    Independent formatting rule fragment engine.
    
    Format rules are:
      1. Stored as standalone .format.yaml files
      2. Hash-stable (same rules = same hash = same KV cache key)
      3. Injected into system prompt ONLY when triggered by task type
      4. Never mixed with identity preamble
    
    This isolation ensures the preamble cache stays clean and
    formatting rules don't bloat every request.
    """
    
    def __init__(self, formats_dir: Optional[Path] = None):
        self.formats_dir = formats_dir or DEFAULT_FORMATS_DIR
        self._rules: Dict[str, FormatRule] = {}
        self._trigger_index: Dict[str, str] = {}  # trigger word → format name
        self._loaded = False
    
    # ── Loading ─────────────────────────────────────────────
    
    def load(self):
        """Load format rules from disk + builtins."""
        self._load_builtins()
        self._load_from_disk()
        self._build_trigger_index()
        self._loaded = True
        logger.info(f"Loaded {len(self._rules)} format rules "
                     f"with {len(self._trigger_index)} triggers")
    
    def reload(self):
        """Reload all format rules."""
        self._rules.clear()
        self._trigger_index.clear()
        self._loaded = False
        self.load()
    
    # ── Rule Management ─────────────────────────────────────
    
    def add_rule(self, rule: FormatRule):
        """Add or update a format rule."""
        self._rules[rule.name] = rule
        for trigger in rule.triggers:
            self._trigger_index[trigger.lower()] = rule.name
        logger.debug(f"Added format rule: {rule.name}")
    
    def remove_rule(self, name: str) -> bool:
        """Remove a format rule."""
        if name not in self._rules:
            return False
        rule = self._rules.pop(name)
        for trigger in rule.triggers:
            if self._trigger_index.get(trigger.lower()) == name:
                del self._trigger_index[trigger.lower()]
        logger.info(f"Removed format rule: {name}")
        return True
    
    def get_rule(self, name: str) -> Optional[FormatRule]:
        """Get a specific format rule by name."""
        if not self._loaded:
            self.load()
        return self._rules.get(name)
    
    def list_rules(self) -> List[dict]:
        """List all format rules."""
        if not self._loaded:
            self.load()
        return [r.to_dict() for r in sorted(self._rules.values(), key=lambda r: r.name)]
    
    # ── Format Detection ────────────────────────────────────
    
    def detect_format(self, task: str) -> List[str]:
        """
        Detect which format rules apply to a task.
        
        Returns:
            List of format rule names triggered by the task.
        """
        if not self._loaded:
            self.load()
        
        task_lower = task.lower()
        detected: Set[str] = set()
        
        for trigger, rule_name in self._trigger_index.items():
            if trigger in task_lower:
                detected.add(rule_name)
        
        return sorted(detected)
    
    def format_for(self, task: str) -> str:
        """
        Get combined formatting fragment for a task.
        
        Returns:
            Formatted text fragment ready for system prompt injection.
            Empty string if no rules triggered.
        """
        if not self._loaded:
            self.load()
        
        rule_names = self.detect_format(task)
        if not rule_names:
            return ""
        
        fragments = []
        for name in rule_names:
            rule = self._rules.get(name)
            if rule:
                fragments.append(rule.formatted)
        
        if not fragments:
            return ""
        
        return "\n\n".join(fragments)
    
    def format_for_system_prompt(self, task: str) -> str:
        """
        Get formatting fragment encapsulated for system prompt injection.
        
        This is separated from the identity preamble so the preamble's
        KV cache stays clean.
        """
        fragment = self.format_for(task)
        if not fragment:
            return ""
        
        return (
            "## OUTPUT FORMATTING RULES (apply to your response)\n"
            "The following formatting rules apply to this specific task:\n\n"
            f"{fragment}\n\n"
            "Follow these rules for your output. These rules are task-specific "
            "and do not affect your identity or capabilities."
        )
    
    # ── Fragment Hash ───────────────────────────────────────
    
    def get_fragment_hash(self, task: str) -> str:
        """
        Get a hash for the formatting fragment applicable to this task.
        
        Useful for cache keys — same task type = same format rules = same hash.
        """
        rule_names = self.detect_format(task)
        if not rule_names:
            return "no-format"
        
        hashes = []
        for name in rule_names:
            rule = self._rules.get(name)
            if rule:
                hashes.append(rule.content_hash)
        
        combined = "+".join(sorted(hashes))
        return hashlib.sha256(combined.encode()).hexdigest()[:16]
    
    # ── Internal ────────────────────────────────────────────
    
    def _load_builtins(self):
        """Load built-in format rules."""
        for name, data in BUILTIN_FORMATS.items():
            self.add_rule(FormatRule.from_dict(data))
    
    def _load_from_disk(self):
        """Load format rules from .meshctx/formats/ directory."""
        if not self.formats_dir.exists():
            return
        
        for filepath in self.formats_dir.glob(f"*{FORMAT_EXT}"):
            try:
                rule = self._parse_format_file(filepath)
                if rule:
                    self.add_rule(rule)
            except Exception as e:
                logger.warning(f"Failed to load format file {filepath.name}: {e}")
    
    def _parse_format_file(self, filepath: Path) -> Optional[FormatRule]:
        """Parse a .format.yaml file."""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        data = {}
        current_key = None
        current_rules = []
        in_rules = False
        
        for line in content.split("\n"):
            if line.startswith("#"):
                continue
            
            if line.startswith("rules:") and not line.startswith("  "):
                in_rules = True
                continue
            
            if in_rules:
                if line.startswith("  - "):
                    current_rules.append(line[4:].strip())
                    continue
                elif not line.strip() or line.startswith("  "):
                    continue
                else:
                    in_rules = False
                    data["rules"] = current_rules
            
            if ":" in line and not line.startswith("  "):
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip().strip('"')
                if val.startswith("[") and val.endswith("]"):
                    data[key] = [x.strip().strip('"') for x in val[1:-1].split(",") if x.strip()]
                else:
                    data[key] = val
        
        if in_rules:
            data["rules"] = current_rules
        
        name = data.get("name", filepath.stem.replace(".format", ""))
        if not data.get("rules"):
            return None
        
        return FormatRule(
            name=name,
            description=data.get("description", ""),
            triggers=data.get("triggers", []),
            rules=data.get("rules", []),
        )
    
    def _build_trigger_index(self):
        """Build reverse index: trigger word → rule name."""
        self._trigger_index.clear()
        for name, rule in self._rules.items():
            for trigger in rule.triggers:
                self._trigger_index[trigger.lower()] = name
    
    # ── Stats ───────────────────────────────────────────────
    
    def stats(self) -> dict:
        """Format engine statistics."""
        if not self._loaded:
            self.load()
        return {
            "total_rules": len(self._rules),
            "total_triggers": len(self._trigger_index),
            "rule_names": sorted(self._rules.keys()),
            "loaded": self._loaded,
        }


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_engine: Optional[TUIFormatEngine] = None


def get_tui_format_engine(formats_dir: Optional[Path] = None) -> TUIFormatEngine:
    """Get or create the global TUI format engine."""
    global _engine
    if _engine is None:
        _engine = TUIFormatEngine(formats_dir)
        _engine.load()
    return _engine
