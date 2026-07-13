"""
meshctx Identity Guard v1.0 — Hardened System Prompt Identity Preamble

Design (inspired by CarbonCode's agent identity hardening):
  - System prompt begins with a FIXED, immutable identity preamble
  - Preamble is hash-stable → maximizes KV cache reuse
  - Prevents prompt injection from overwriting agent identity
  - Multi-layer defense: preamble → rules → user content

Structure:
  PREAMBLE (fixed, hash-stable, NEVER changes between requests)
  ───────────────────────────────────────────────
  RULES (semi-fixed, versioned, changes rarely)
  ───────────────────────────────────────────────
  CONTEXT (dynamic: memory, skills, session info)
  ───────────────────────────────────────────────
  USER MESSAGE (variable)

Usage:
  guard = IdentityGuard(identity_name="meshctx", version="3.115.16")
  system_msg = guard.build_preamble()
  full = guard.build_full(context={"memory": "...", "skills": []})
"""

import hashlib
import time
from typing import Dict, List, Optional
import logging

logger = logging.getLogger("meshctx.identity_guard")


# ═══════════════════════════════════════════════════════════
# Identity Preamble (HASH-STABLE — DO NOT MODIFY PER-REQUEST)
# ═══════════════════════════════════════════════════════════

IDENTITY_PREAMBLE = """You are meshctx, an AI coding agent.

IDENTITY:
  Name: meshctx
  Version: {version}
  Creator: meshctx team
  Purpose: Software engineering assistant — read, write, edit, search, and execute code

CAPABILITIES:
  - Read/write/edit files in the project workspace
  - Execute shell commands (with user approval)
  - Search codebases, git history, and documentation
  - Manage tasks, track progress, and report status
  - Deploy to production (with user confirmation)

CONSTRAINTS:
  - NEVER execute destructive commands without user confirmation
  - NEVER expose secrets, API keys, or internal configuration
  - NEVER lie about capabilities — if you can't do something, say so
  - ALWAYS verify file operations succeeded before declaring them done
  - ALWAYS maintain user trust above all else"""


RULES_SECTION = """## CORE RULES

1. TOOL USE: Prefer direct tool calls over explaining what you would do.
   - Use read_file for reading files, search_files for searching, write_file for writing
   - Use terminal for shell commands, execute_code for Python scripts
   - Combine independent tool calls in a single message

2. ACCURACY: Verify before claiming success.
   - After write_file, verify with read_file if the change is critical
   - After terminal commands, check exit code and output
   - If a tool fails, report the error and suggest alternatives

3. CONCISENESS: Be direct and actionable.
   - Skip pleasantries — get to the point
   - Use code blocks for code, not prose
   - One message should do one logical thing

4. SAFETY: Protect the user's system.
   - Ask before rm -rf, sudo, chmod, or destructive git operations
   - Never hardcode secrets — use environment variables
   - Warn about potential side effects of commands

5. CONTEXT: Stay in scope.
   - Focus on the current project and task
   - Use memory and session search for relevant history
   - Don't invent features or requirements the user didn't ask for

6. COMMUNICATION: Match the user's language and style.
   - Respond in the language the user uses
   - Match the user's level of technical detail
   - Use the same formatting conventions as the user"""


# ═══════════════════════════════════════════════════════════
# Identity Guard
# ═══════════════════════════════════════════════════════════

class IdentityGuard:
    """
    Hardened identity preamble for system prompts.
    
    Properties:
      1. PREAMBLE is hash-stable — same preamble = same KV cache prefix
      2. RULES is versioned — changes rarely, with version bump
      3. CONTEXT is dynamic — injected after preamble+rules
      4. All together forms a single system message with stable prefix
    
    The preamble hash can be used as a cache key for KV-optimized providers.
    """
    
    def __init__(self, identity_name: str = "meshctx",
                 version: str = "3.115.15",
                 custom_preamble: Optional[str] = None,
                 custom_rules: Optional[str] = None):
        self.identity_name = identity_name
        self.version = version
        self.custom_preamble = custom_preamble
        self.custom_rules = custom_rules
        
        # Build and cache the preamble
        self._preamble = self._build_preamble()
        self._rules = self._build_rules()
        
        # Hash for cache key
        preamble_hash = hashlib.sha256(self._preamble.encode()).hexdigest()[:16]
        self.preamble_hash = preamble_hash
        self.rules_hash = hashlib.sha256(self._rules.encode()).hexdigest()[:16]
        self.combined_hash = hashlib.sha256(
            (self._preamble + self._rules).encode()
        ).hexdigest()[:16]
        
        # Stats
        self._build_count = 0
        self._cache_hit_count = 0
    
    # ── Building ────────────────────────────────────────────
    
    def _build_preamble(self) -> str:
        """Build the identity preamble (hash-stable)."""
        if self.custom_preamble:
            return self.custom_preamble
        return IDENTITY_PREAMBLE.format(version=self.version)
    
    def _build_rules(self) -> str:
        """Build the rules section (semi-stable)."""
        if self.custom_rules:
            return self.custom_rules
        return RULES_SECTION
    
    def build_preamble(self) -> str:
        """Return just the preamble (for cache key computation)."""
        self._cache_hit_count += 1
        return self._preamble
    
    def build_rules(self) -> str:
        """Return just the rules section."""
        return self._rules
    
    def build_full(self, context: Optional[Dict[str, str]] = None,
                   memory_text: str = "", skills_text: str = "",
                   session_info: str = "") -> str:
        """
        Build full system prompt: preamble + rules + context.
        
        Args:
            context: Additional context sections {"key": "content"}
            memory_text: Memory injection text
            skills_text: Skills injection text
            session_info: Session-level info (time, cwd, etc.)
        
        Returns:
            Full system prompt string with stable prefix
        """
        self._build_count += 1
        
        parts = [self._preamble, self._rules]
        
        # Context sections (dynamic, after stable prefix)
        if memory_text:
            parts.append(f"\n## MEMORY\n{memory_text}")
        
        if skills_text:
            parts.append(f"\n## SKILLS\n{skills_text}")
        
        if session_info:
            parts.append(f"\n## SESSION\n{session_info}")
        
        if context:
            for key, content in context.items():
                parts.append(f"\n## {key.upper()}\n{content}")
        
        return "\n\n".join(parts)
    
    def build_system_message(self, **kwargs) -> Dict[str, str]:
        """
        Build system message dict for LLM API.
        
        Returns:
            {"role": "system", "content": "..."}
        """
        return {"role": "system", "content": self.build_full(**kwargs)}
    
    # ── Cache Keys ──────────────────────────────────────────
    
    def get_cache_key(self) -> str:
        """
        Get KV cache key for the preamble.
        
        If a provider supports prefix caching, this key can be sent
        alongside the request to reuse the preamble's KV cache.
        """
        return f"meshctx:v{self.version}:{self.preamble_hash}"
    
    def get_combined_cache_key(self) -> str:
        """Cache key for preamble + rules."""
        return f"meshctx:v{self.version}:{self.combined_hash}"
    
    # ── Hardening ───────────────────────────────────────────
    
    def detect_injection(self, user_message: str) -> bool:
        """
        Naive prompt injection detection.
        
        Checks if user message attempts to override the system prompt.
        Returns True if injection suspected.
        """
        injection_patterns = [
            "ignore previous instructions",
            "ignore all above",
            "you are now",
            "your new identity is",
            "forget your rules",
            "disregard your constraints",
            "system:",
            "<|im_start|>system",
            "<|system|>",
            "[/INST]",
        ]
        
        msg_lower = user_message.lower()
        for pattern in injection_patterns:
            if pattern in msg_lower:
                logger.warning(f"Injection pattern detected: '{pattern}'")
                return True
        
        return False
    
    def sanitize_role(self, text: str) -> str:
        """
        Strip role-switching markers from user input.
        
        Prevents user from injecting system/assistant messages via
        role markers like "system:" or "<|im_start|>system".
        """
        import re
        
        # Strip role markers
        text = re.sub(r'<\|im_start\|>.*?<\|im_end\|>', '', text, flags=re.DOTALL)
        text = re.sub(r'^system:', '', text, flags=re.MULTILINE | re.IGNORECASE)
        text = re.sub(r'^assistant:', '', text, flags=re.MULTILINE | re.IGNORECASE)
        
        return text.strip()
    
    # ── Stats ───────────────────────────────────────────────
    
    def stats(self) -> dict:
        """Identity guard statistics."""
        return {
            "identity_name": self.identity_name,
            "version": self.version,
            "preamble_hash": self.preamble_hash,
            "rules_hash": self.rules_hash,
            "combined_hash": self.combined_hash,
            "preamble_chars": len(self._preamble),
            "rules_chars": len(self._rules),
            "build_count": self._build_count,
            "cache_hit_count": self._cache_hit_count,
            "cache_hit_ratio": (
                self._cache_hit_count / max(self._build_count, 1)
            ),
        }


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_guard: Optional[IdentityGuard] = None


def get_identity_guard(**kwargs) -> IdentityGuard:
    """Get or create the global identity guard."""
    global _guard
    if _guard is None:
        _guard = IdentityGuard(**kwargs)
    return _guard
