"""
meshctx Tool-Call Repair Layer v1.0 — JSON Repair for Broken Tool Calls

Design (inspired by CarbonCode's tool-call repair pattern):
  - LLMs sometimes produce malformed JSON in tool calls
  - This layer intercepts failed tool calls, attempts repair, and retries
  - Repair strategies (in order):
    1. Trailing comma removal
    2. Missing closing brace/bracket
    3. Unescaped quotes in string values
    4. Single quotes → double quotes
    5. Truncated JSON completion
    6. Schema-based reconstruction (last resort)

Usage:
  repair = ToolRepair()
  fixed = repair.fix('{"tool": "read_file", "args": {"path": "/tmp/file.txt",}')
  # → {"tool": "read_file", "args": {"path": "/tmp/file.txt"}}
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger("meshctx.tool_repair")


# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

MAX_REPAIR_ATTEMPTS = 5
MAX_RECURSION_DEPTH = 3


# ═══════════════════════════════════════════════════════════
# Tool-Call Repair Engine
# ═══════════════════════════════════════════════════════════

class ToolRepair:
    """
    Multi-strategy JSON repair for LLM tool calls.
    
    Each strategy is tried in order until one succeeds.
    Failed repair attempts are logged for debugging.
    """
    
    def __init__(self):
        self.repair_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.strategy_counts: Dict[str, int] = {
            "trailing_comma": 0,
            "missing_bracket": 0,
            "unescape_quotes": 0,
            "single_to_double": 0,
            "truncated_complete": 0,
            "schema_reconstruct": 0,
            "clean_control": 0,
        }
    
    # ── Main API ────────────────────────────────────────────
    
    def fix(self, text: str, schema: Optional[Dict] = None) -> Tuple[str, bool, str]:
        """
        Attempt to repair broken JSON tool call.
        
        Args:
            text: The potentially broken JSON string
            schema: Optional expected schema for reconstruction
        
        Returns:
            (repaired_json, success, strategy_used)
        """
        self.repair_count += 1
        
        # Fast path: already valid
        if self._is_valid(text):
            self.success_count += 1
            return text, True, "valid"
        
        # Try repair strategies in order
        repaired, strategy = self._try_repair(text, schema)
        
        if repaired and self._is_valid(repaired):
            self.success_count += 1
            self.strategy_counts[strategy] = self.strategy_counts.get(strategy, 0) + 1
            logger.info(f"Tool repair succeeded via '{strategy}': "
                         f"{len(text)} → {len(repaired)} chars")
            return repaired, True, strategy
        
        self.fail_count += 1
        logger.warning(f"Tool repair FAILED after {MAX_REPAIR_ATTEMPTS} attempts: "
                        f"original={text[:100]}...")
        return text, False, "all_failed"
    
    def fix_or_raise(self, text: str, schema: Optional[Dict] = None) -> str:
        """
        Repair or raise ValueError with diagnostic info.
        Used when a tool call MUST succeed.
        """
        repaired, ok, strategy = self.fix(text, schema)
        if not ok:
            raise ValueError(
                f"Tool call repair failed. Original: {text[:200]}... "
                f"Attempts: {self.repair_count}"
            )
        return repaired
    
    # ── Batch Repair ───────────────────────────────────────
    
    def fix_batch(self, items: List[str], schema: Optional[Dict] = None) -> List[Tuple[str, bool, str]]:
        """Repair multiple tool calls."""
        return [self.fix(item, schema) for item in items]
    
    # ── Repair Strategies ───────────────────────────────────
    
    def _try_repair(self, text: str, schema: Optional[Dict] = None) -> Tuple[Optional[str], str]:
        """
        Try all repair strategies in order.
        
        Returns:
            (repaired_text or None, strategy_name)
        """
        strategies = [
            ("clean_control", self._clean_control_chars),
            ("trailing_comma", self._remove_trailing_commas),
            ("missing_bracket", self._close_missing_brackets),
            ("unescape_quotes", self._unescape_quotes),
            ("single_to_double", self._single_to_double_quotes),
            ("truncated_complete", self._complete_truncated),
        ]
        
        for name, fn in strategies:
            try:
                result = fn(text)
                if result and result != text:
                    if self._is_valid(result):
                        return result, name
            except Exception as e:
                logger.debug(f"Strategy '{name}' failed: {e}")
        
        # Last resort: schema-based reconstruction
        if schema:
            try:
                result = self._schema_reconstruct(text, schema)
                if result and self._is_valid(result):
                    return result, "schema_reconstruct"
            except Exception as e:
                logger.debug(f"Schema reconstruction failed: {e}")
        
        return None, "all_failed"
    
    # ── Strategy 1: Clean Control Characters ────────────────
    
    def _clean_control_chars(self, text: str) -> str:
        """Remove unescaped control characters from JSON string."""
        # Replace common control chars (except \n, \t, \r which are valid in JSON strings)
        cleaned = text
        # Remove null bytes
        cleaned = cleaned.replace('\x00', '')
        # Replace other control chars with space
        cleaned = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f]', ' ', cleaned)
        return cleaned
    
    # ── Strategy 2: Remove Trailing Commas ──────────────────
    
    def _remove_trailing_commas(self, text: str) -> str:
        """Remove trailing commas before closing brackets/braces."""
        # Pattern: comma followed by optional whitespace then ] or }
        return re.sub(r',\s*([]}])', r'\1', text)
    
    # ── Strategy 3: Close Missing Brackets ──────────────────
    
    def _close_missing_brackets(self, text: str) -> str:
        """Add missing closing brackets/braces."""
        # Count open vs close brackets
        brackets = {"{": "}", "[": "]"}
        stack = []
        in_string = False
        escape_next = False
        
        for ch in text:
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in brackets:
                stack.append(brackets[ch])
            elif ch in brackets.values():
                if stack and stack[-1] == ch:
                    stack.pop()
        
        # Add missing closing brackets in reverse order
        closing = "".join(reversed(stack))
        return text + closing
    
    # ── Strategy 4: Unescape Internal Quotes ────────────────
    
    def _unescape_quotes(self, text: str) -> str:
        """Fix unescaped double quotes inside JSON strings."""
        # This is tricky — we look for patterns where a quote appears
        # mid-string (between opening quote and closing quote of a string value)
        
        result = []
        in_string = False
        escape_next = False
        depth = 0  # brace/bracket depth
        
        for i, ch in enumerate(text):
            if escape_next:
                escape_next = False
                result.append(ch)
                continue
            
            if ch == '\\':
                escape_next = True
                result.append(ch)
                continue
            
            if ch == '"' and not in_string:
                in_string = True
                result.append(ch)
                continue
            
            if ch == '"' and in_string:
                # Check if this is the closing quote of a string value
                # Look ahead: expect comma, colon, bracket, whitespace
                remainder = text[i+1:].lstrip()
                if not remainder or remainder[0] in ',:}]':
                    in_string = False
                    result.append(ch)
                else:
                    # This is an unescaped quote inside a string
                    result.append('\\"')
                continue
            
            if not in_string:
                if ch in '{[':
                    depth += 1
                elif ch in '}]':
                    depth = max(0, depth - 1)
            
            result.append(ch)
        
        return "".join(result)
    
    # ── Strategy 5: Single Quotes → Double Quotes ───────────
    
    def _single_to_double_quotes(self, text: str) -> str:
        """Convert Python-style single-quote dict to JSON double quotes."""
        # Only try if text looks like it might be Python dict (no double quotes)
        if '"' in text:
            return text
        
        # Replace single quotes around keys and string values
        # Key pattern: 'key':
        text = re.sub(r"'(\w+)'\s*:", r'"\1":', text)
        # String value pattern: : 'value'
        text = re.sub(r":\s*'([^']*)'", r': "\1"', text)
        # Other single-quoted strings
        text = text.replace("'", '"')
        
        return text
    
    # ── Strategy 6: Complete Truncated JSON ─────────────────
    
    def _complete_truncated(self, text: str) -> str:
        """Attempt to complete truncated JSON by removing incomplete final element."""
        # Remove trailing incomplete key-value pair
        # Pattern: , "key":  (no closing value)
        text = re.sub(r',\s*"[^"]*"\s*:\s*$', '', text)
        # Remove trailing incomplete string
        text = re.sub(r',\s*"[^"]*$', '', text)
        # Remove trailing incomplete array element
        text = re.sub(r',\s*[\[{][^}\]]*$', '', text)
        
        # Close any remaining brackets
        text = self._close_missing_brackets(text)
        text = self._remove_trailing_commas(text)
        
        return text
    
    # ── Strategy 7: Schema-Based Reconstruction ─────────────
    
    def _schema_reconstruct(self, text: str, schema: Dict) -> Optional[str]:
        """
        Attempt to extract values from broken JSON using schema as template.
        
        This is last-resort: try regex-extracting known keys from schema
        and re-constructing a valid JSON object.
        """
        if not schema or "properties" not in schema:
            return None
        
        extracted = {}
        for key, prop in schema.get("properties", {}).items():
            # Try to find the key in the broken text
            pattern = rf'"[{key}]"\s*:\s*(.+?)(?:,|\s*[}}]|$)'
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                # Try to parse the value based on type
                prop_type = prop.get("type", "string")
                try:
                    if prop_type == "number":
                        extracted[key] = float(value)
                    elif prop_type == "integer":
                        extracted[key] = int(value)
                    elif prop_type == "boolean":
                        extracted[key] = value.lower() in ("true", "1", "yes")
                    elif prop_type == "object":
                        extracted[key] = json.loads(value) if value.startswith("{") else {}
                    elif prop_type == "array":
                        extracted[key] = json.loads(value) if value.startswith("[") else []
                    else:
                        extracted[key] = value.strip('"\'')
                except (ValueError, json.JSONDecodeError):
                    extracted[key] = value.strip('"\'')
        
        if not extracted:
            return None
        
        return json.dumps(extracted, indent=2)
    
    # ── Helpers ─────────────────────────────────────────────
    
    def _is_valid(self, text: str) -> bool:
        """Check if text is valid JSON."""
        try:
            json.loads(text)
            return True
        except json.JSONDecodeError:
            return False
    
    def validate_and_diagnose(self, text: str) -> Dict[str, Any]:
        """
        Validate JSON and return diagnostic info.
        
        Returns:
            {"valid": bool, "error": str|null, "line": int|null, "col": int|null}
        """
        try:
            json.loads(text)
            return {"valid": True, "error": None, "line": None, "col": None}
        except json.JSONDecodeError as e:
            return {
                "valid": False,
                "error": str(e),
                "line": e.lineno,
                "col": e.colno,
                "pos": e.pos,
            }
    
    # ── Stats ────────────────────────────────────────────────
    
    def stats(self) -> dict:
        """Repair statistics."""
        total = self.repair_count
        return {
            "total_attempts": total,
            "successes": self.success_count,
            "failures": self.fail_count,
            "success_rate": self.success_count / max(total, 1),
            "strategy_usage": dict(self.strategy_counts),
        }
    
    def get_report(self) -> str:
        """Human-readable repair report."""
        s = self.stats()
        lines = [
            f"Tool Repair Report",
            f"──────────────────",
            f"Attempts: {s['total_attempts']}",
            f"Success: {s['successes']} ({s['success_rate']:.1%})",
            f"Failures: {s['failures']}",
            f"",
            f"Strategy usage:",
        ]
        for strategy, count in sorted(s["strategy_usage"].items(), key=lambda x: -x[1]):
            lines.append(f"  {strategy}: {count}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_repair: Optional[ToolRepair] = None


def get_tool_repair() -> ToolRepair:
    """Get or create the global tool repair engine."""
    global _repair
    if _repair is None:
        _repair = ToolRepair()
    return _repair
