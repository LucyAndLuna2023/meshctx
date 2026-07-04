"""
meshctx Prompt Template Registry v1.0 — Versioned Prompt Template Management

Design (inspired by CarbonCode prompt-template-registry):
  - YAML-based template files in .meshctx/prompts/
  - Published/Draft lifecycle
  - {{variable}} extraction + validation
  - Render audit records
  - Version immutability

Lifecycle:
  draft → published → deprecated → archived

Usage:
  registry = PromptRegistry()
  registry.create("code_review", "Review {{file}} for {{focus}}.")
  registry.publish("code_review")
  rendered = registry.render("code_review", {"file": "src/app.py", "focus": "security"})
"""

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import logging

logger = logging.getLogger("meshctx.prompt_registry")


# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

VARIABLE_RE = re.compile(r'\{\{(\w+)\}\}')  # {{variable_name}}
DEFAULT_PROMPTS_DIR = Path.home() / ".meshctx" / "prompts"
TEMPLATE_EXT = ".prompt.yaml"


# ═══════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════

class TemplateStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


# ═══════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════

@dataclass
class TemplateVersion:
    """Immutable version snapshot."""
    version: int
    template_text: str
    system_prompt: str = ""
    created_at: float = field(default_factory=time.time)
    change_note: str = ""
    rendered_count: int = 0
    sha256: str = ""
    
    def __post_init__(self):
        if not self.sha256:
            self.sha256 = hashlib.sha256(
                (self.system_prompt + self.template_text).encode()
            ).hexdigest()[:16]


@dataclass
class PromptTemplate:
    """Managed prompt template with lifecycle."""
    template_id: str = field(default_factory=lambda: f"tpl_{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    template_text: str = ""         # Contains {{variable}} placeholders
    system_prompt: str = ""         # Optional system-level instructions
    variables: Set[str] = field(default_factory=set)
    status: TemplateStatus = TemplateStatus.DRAFT
    tags: List[str] = field(default_factory=list)
    category: str = "general"
    versions: List[TemplateVersion] = field(default_factory=list)
    current_version: int = 0
    created_at: float = field(default_factory=time.time)
    published_at: Optional[float] = None
    
    @property
    def latest(self) -> Optional[TemplateVersion]:
        if self.versions:
            return self.versions[-1]
        return None
    
    @property
    def is_published(self) -> bool:
        return self.status == TemplateStatus.PUBLISHED


@dataclass
class RenderAudit:
    """Audit record for template rendering."""
    audit_id: str = field(default_factory=lambda: f"aud_{uuid.uuid4().hex[:8]}")
    template_name: str = ""
    version: int = 0
    variables: Dict[str, Any] = field(default_factory=dict)
    rendered_at: float = field(default_factory=time.time)
    rendered_text: str = ""
    estimated_tokens: int = 0
    sha256: str = ""


# ═══════════════════════════════════════════════════════════
# Prompt Registry
# ═══════════════════════════════════════════════════════════

class PromptRegistry:
    """
    Versioned prompt template registry.
    
    Core operations:
      - create(name, template_text) → PromptTemplate
      - publish(name) → marks drafted template as published
      - deprecate(name) → marks as deprecated (render still works)
      - archive(name) → disables rendering
      - render(name, variables) → RenderedPrompt with validation
      - get(name, version=N) → get specific version
      
    Audit trail:
      - Every render creates a RenderAudit record
      - Audit records are persisted in .meshctx/prompts/_audit/
    """
    
    def __init__(self, prompts_dir: Optional[Path] = None):
        self.prompts_dir = prompts_dir or DEFAULT_PROMPTS_DIR
        self._templates: Dict[str, PromptTemplate] = {}
        self._audit_log: List[RenderAudit] = []
        self._render_count: int = 0
        
        # Ensure directories exist
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        (self.prompts_dir / "_audit").mkdir(parents=True, exist_ok=True)
        
        # Load existing templates from disk
        self._load_from_disk()
    
    # ── Lifecycle Management ────────────────────────────────
    
    def create(
        self,
        name: str,
        template_text: str,
        system_prompt: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
        category: str = "general",
    ) -> PromptTemplate:
        """
        Create a new prompt template (draft status).
        
        Args:
            name: Unique template name (e.g. "code_review")
            template_text: Template with {{variable}} placeholders
            system_prompt: System-level instructions
            description: Human-readable description
            tags: Categorization tags
            category: Broad grouping (general, code, analysis, creative)
        
        Returns:
            PromptTemplate in DRAFT status
        """
        if name in self._templates:
            logger.warning(f"Template '{name}' exists — updating")
            return self.update(name, template_text, system_prompt, description, tags)
        
        variables = self._extract_variables(template_text)
        # Also extract from system_prompt
        if system_prompt:
            variables.update(self._extract_variables(system_prompt))
        
        tmpl = PromptTemplate(
            name=name,
            description=description,
            template_text=template_text,
            system_prompt=system_prompt,
            variables=variables,
            status=TemplateStatus.DRAFT,
            tags=tags or [],
            category=category,
        )
        
        # Create first version
        v1 = TemplateVersion(
            version=1,
            template_text=template_text,
            system_prompt=system_prompt,
            change_note="Initial draft",
        )
        tmpl.versions.append(v1)
        tmpl.current_version = 1
        
        self._templates[name] = tmpl
        self._save_template(tmpl)
        logger.info(f"Created template '{name}' v1 (draft) [{len(variables)} variables]")
        
        return tmpl
    
    def publish(self, name: str, change_note: str = "") -> bool:
        """
        Publish a draft template → available for rendering.
        
        Templates can only be published from DRAFT status.
        Once published, the current version is locked.
        """
        tmpl = self._get(name)
        if not tmpl:
            return False
        
        if tmpl.status != TemplateStatus.DRAFT:
            logger.warning(f"Cannot publish '{name}': status is {tmpl.status.value}")
            return False
        
        tmpl.status = TemplateStatus.PUBLISHED
        tmpl.published_at = time.time()
        if tmpl.latest and change_note:
            tmpl.latest.change_note = change_note
        
        self._save_template(tmpl)
        logger.info(f"Published template '{name}' v{tmpl.current_version}")
        return True
    
    def deprecate(self, name: str, reason: str = "") -> bool:
        """Mark template as deprecated (still renderable but warns)."""
        tmpl = self._get(name)
        if not tmpl:
            return False
        tmpl.status = TemplateStatus.DEPRECATED
        if reason and tmpl.latest:
            tmpl.latest.change_note = f"Deprecated: {reason}"
        self._save_template(tmpl)
        logger.info(f"Deprecated template '{name}': {reason}")
        return True
    
    def archive(self, name: str) -> bool:
        """Archive template (disables rendering)."""
        tmpl = self._get(name)
        if not tmpl:
            return False
        tmpl.status = TemplateStatus.ARCHIVED
        self._save_template(tmpl)
        logger.info(f"Archived template '{name}'")
        return True
    
    def update(
        self, name: str, template_text: str,
        system_prompt: str = "", description: str = "",
        tags: Optional[List[str]] = None, change_note: str = "",
    ) -> Optional[PromptTemplate]:
        """
        Update a template, creating a NEW version.
        
        If the template is PUBLISHED, the previous version stays immutable.
        The new version becomes the current one (DRAFT if was published).
        """
        tmpl = self._get(name)
        if not tmpl:
            return None
        
        variables = self._extract_variables(template_text)
        if system_prompt:
            variables.update(self._extract_variables(system_prompt))
        
        new_version = tmpl.current_version + 1
        v = TemplateVersion(
            version=new_version,
            template_text=template_text,
            system_prompt=system_prompt,
            change_note=change_note or f"Updated to v{new_version}",
        )
        
        tmpl.versions.append(v)
        tmpl.current_version = new_version
        tmpl.template_text = template_text
        tmpl.system_prompt = system_prompt
        tmpl.variables = variables
        if description:
            tmpl.description = description
        if tags is not None:
            tmpl.tags = tags
        
        # If it was published, bump back to draft on update
        if tmpl.status == TemplateStatus.PUBLISHED:
            tmpl.status = TemplateStatus.DRAFT
            logger.info(f"Template '{name}' reverted to draft (updated to v{new_version})")
        
        self._save_template(tmpl)
        logger.info(f"Updated template '{name}' to v{new_version} [{len(variables)} variables]")
        
        return tmpl
    
    # ── Rendering ───────────────────────────────────────────
    
    def render(
        self, name: str, variables: Dict[str, Any],
        version: Optional[int] = None, audit: bool = True
    ) -> str:
        """
        Render a template with variables.
        
        Args:
            name: Template name
            variables: Key-value map for template placeholders
            version: Specific version to render (None = latest)
            audit: Whether to create an audit record
        
        Returns:
            Rendered prompt string
        
        Raises:
            ValueError: If template not found, archived, or missing required variables
        """
        tmpl = self._get(name)
        if not tmpl:
            raise ValueError(f"Template '{name}' not found")
        
        if tmpl.status == TemplateStatus.ARCHIVED:
            raise ValueError(f"Template '{name}' is archived — cannot render")
        
        if tmpl.status == TemplateStatus.DEPRECATED:
            logger.warning(f"Rendering deprecated template '{name}'")
        
        # Get version
        if version is not None:
            ver = next((v for v in tmpl.versions if v.version == version), None)
            if not ver:
                raise ValueError(f"Version {version} not found for template '{name}'")
        else:
            ver = tmpl.latest
            if not ver:
                raise ValueError(f"No versions for template '{name}'")
        
        # Validate variables
        required = self._extract_variables(ver.template_text)
        missing = required - set(variables.keys())
        if missing:
            raise ValueError(
                f"Missing required variables for '{name}': {', '.join(sorted(missing))}"
            )
        
        # Render
        rendered = ver.template_text
        for k, v in variables.items():
            rendered = rendered.replace(f"{{{{{k}}}}}", str(v))
        
        # Prepend system prompt if exists
        if ver.system_prompt:
            rendered = ver.system_prompt + "\n\n" + rendered
        
        # Update version render count
        ver.rendered_count += 1
        
        # Audit
        if audit:
            self._record_audit(name, ver.version, variables, rendered)
        
        self._render_count += 1
        return rendered
    
    def render_safe(self, name: str, variables: Dict[str, Any], **kwargs) -> Tuple[Optional[str], Optional[str]]:
        """
        Safe render: (result, error) tuple instead of raising.
        
        Returns:
            (rendered_text, None) on success
            (None, error_message) on failure
        """
        try:
            return self.render(name, variables, **kwargs), None
        except Exception as e:
            return None, str(e)
    
    # ── Version Access ──────────────────────────────────────
    
    def get_version(self, name: str, version: int) -> Optional[TemplateVersion]:
        """Get a specific version of a template."""
        tmpl = self._get(name)
        if not tmpl:
            return None
        return next((v for v in tmpl.versions if v.version == version), None)
    
    def get_latest(self, name: str) -> Optional[TemplateVersion]:
        """Get latest version of a template."""
        tmpl = self._get(name)
        return tmpl.latest if tmpl else None
    
    def list_versions(self, name: str) -> List[dict]:
        """List all versions of a template."""
        tmpl = self._get(name)
        if not tmpl:
            return []
        return [
            {
                "version": v.version,
                "sha256": v.sha256,
                "created_at": v.created_at,
                "change_note": v.change_note,
                "rendered_count": v.rendered_count,
            }
            for v in tmpl.versions
        ]
    
    # ── Listing ─────────────────────────────────────────────
    
    def list_templates(self, status: Optional[str] = None, category: Optional[str] = None) -> List[dict]:
        """List templates, optionally filtered."""
        result = []
        for tmpl in self._templates.values():
            if status and tmpl.status.value != status:
                continue
            if category and tmpl.category != category:
                continue
            result.append({
                "name": tmpl.name,
                "description": tmpl.description,
                "status": tmpl.status.value,
                "category": tmpl.category,
                "version": tmpl.current_version,
                "variables": sorted(tmpl.variables),
                "tags": tmpl.tags,
                "published_at": tmpl.published_at,
            })
        return sorted(result, key=lambda t: t["name"])
    
    def get_template_info(self, name: str) -> Optional[dict]:
        """Get full info for a template."""
        tmpl = self._get(name)
        if not tmpl:
            return None
        return {
            "template_id": tmpl.template_id,
            "name": tmpl.name,
            "description": tmpl.description,
            "status": tmpl.status.value,
            "category": tmpl.category,
            "current_version": tmpl.current_version,
            "variables": sorted(tmpl.variables),
            "tags": tmpl.tags,
            "versions": self.list_versions(name),
            "created_at": tmpl.created_at,
            "published_at": tmpl.published_at,
        }
    
    # ── Built-in Templates ──────────────────────────────────
    
    def ensure_builtins(self):
        """Ensure built-in templates exist (idempotent)."""
        builtins = [
            ("code_review", "Review the following code:\n```\n{{file_content}}\n```\nFocus on: {{focus}}", "code"),
            ("bug_fix", "Fix this bug:\n```\n{{code}}\n```\nError: {{error}}", "code"),
            ("refactor", "Refactor `{{file}}` to improve {{aspect}}. Keep behavior identical.", "code"),
            ("explain", "Explain `{{concept}}` in {{style}} style for a {{audience}} audience.", "general"),
            ("summarize", "Summarize the following:\n\n{{content}}\n\nFormat: {{format}}", "general"),
            ("plan_task", "Plan the execution of:\n\n{{task}}\n\nBreak into {{granularity}}-grained steps.", "analysis"),
        ]
        
        for name, text, cat in builtins:
            if name not in self._templates:
                self.create(name, text, category=cat)
                self.publish(name)
                logger.info(f"Built-in template '{name}' created and published")
    
    # ── Internal Helpers ────────────────────────────────────
    
    def _get(self, name: str) -> Optional[PromptTemplate]:
        return self._templates.get(name)
    
    def _extract_variables(self, text: str) -> Set[str]:
        """Extract {{variable}} names from template text."""
        return set(VARIABLE_RE.findall(text))
    
    def _record_audit(self, name: str, version: int,
                      variables: Dict[str, Any], rendered: str):
        """Create and persist an audit record."""
        audit = RenderAudit(
            template_name=name,
            version=version,
            variables=variables,
            rendered_text=rendered,
            estimated_tokens=len(rendered) // 4,
            sha256=hashlib.sha256(rendered.encode()).hexdigest()[:16],
        )
        self._audit_log.append(audit)
        
        # Persist audit (keep only last 1000)
        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-1000:]
        
        # Write audit file
        audit_file = self.prompts_dir / "_audit" / f"{audit.audit_id}.json"
        try:
            with open(audit_file, "w") as f:
                json.dump({
                    "audit_id": audit.audit_id,
                    "template_name": audit.template_name,
                    "version": audit.version,
                    "variables": audit.variables,
                    "rendered_at": audit.rendered_at,
                    "estimated_tokens": audit.estimated_tokens,
                    "sha256": audit.sha256,
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write audit: {e}")
    
    # ── Disk Persistence ────────────────────────────────────
    
    def _save_template(self, tmpl: PromptTemplate):
        """Save template to YAML file."""
        filepath = self.prompts_dir / f"{tmpl.name}{TEMPLATE_EXT}"
        
        # Build YAML manually (no yaml dependency)
        lines = [
            f"# meshctx Prompt Template: {tmpl.name}",
            f"# Status: {tmpl.status.value} | Version: {tmpl.current_version}",
            f"template_id: \"{tmpl.template_id}\"",
            f"name: \"{tmpl.name}\"",
            f"description: \"{tmpl.description}\"",
            f"category: \"{tmpl.category}\"",
            f"status: \"{tmpl.status.value}\"",
            f"current_version: {tmpl.current_version}",
            f"tags: [{', '.join(repr(t) for t in tmpl.tags)}]",
            f"created_at: {tmpl.created_at}",
        ]
        if tmpl.published_at:
            lines.append(f"published_at: {tmpl.published_at}")
        
        lines.append("")
        lines.append(f"system_prompt: |")
        for sp_line in tmpl.system_prompt.split("\n"):
            lines.append(f"  {sp_line}")
        
        lines.append("")
        lines.append(f"template_text: |")
        for tt_line in tmpl.template_text.split("\n"):
            lines.append(f"  {tt_line}")
        
        lines.append("")
        lines.append("versions:")
        for v in tmpl.versions:
            lines.append(f"  - version: {v.version}")
            lines.append(f"    sha256: \"{v.sha256}\"")
            lines.append(f"    created_at: {v.created_at}")
            lines.append(f"    change_note: \"{v.change_note}\"")
            lines.append(f"    rendered_count: {v.rendered_count}")
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as e:
            logger.error(f"Failed to save template '{tmpl.name}': {e}")
    
    def _load_from_disk(self):
        """Load existing templates from disk."""
        if not self.prompts_dir.exists():
            return
        
        for filepath in self.prompts_dir.glob(f"*{TEMPLATE_EXT}"):
            try:
                tmpl = self._parse_template_file(filepath)
                if tmpl:
                    self._templates[tmpl.name] = tmpl
            except Exception as e:
                logger.warning(f"Failed to load template from {filepath.name}: {e}")
        
        logger.info(f"Loaded {len(self._templates)} templates from {self.prompts_dir}")
    
    def _parse_template_file(self, filepath: Path) -> Optional[PromptTemplate]:
        """Parse a .prompt.yaml file into a PromptTemplate."""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Simple YAML parsing
        data = {}
        current_key = None
        current_block = []
        in_block = False
        
        for line in content.split("\n"):
            if line.startswith("#"):
                continue
            if in_block:
                if line.startswith("  "):
                    current_block.append(line[2:])
                    continue
                else:
                    data[current_key] = "\n".join(current_block)
                    current_block = []
                    in_block = False
            
            if ":" in line and not line.startswith("  "):
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip().strip('"')
                if val == "|":
                    in_block = True
                    current_key = key
                elif val.startswith("[") and val.endswith("]"):
                    data[key] = [x.strip().strip('"') for x in val[1:-1].split(",") if x.strip()]
                elif val:
                    data[key] = val
        
        if in_block:
            data[current_key] = "\n".join(current_block)
        
        name = data.get("name", filepath.stem.replace(".prompt", ""))
        return PromptTemplate(
            template_id=data.get("template_id", f"tpl_{uuid.uuid4().hex[:8]}"),
            name=name,
            description=data.get("description", ""),
            template_text=data.get("template_text", ""),
            system_prompt=data.get("system_prompt", ""),
            variables=self._extract_variables(data.get("template_text", "")),
            status=TemplateStatus(data.get("status", "draft")),
            tags=data.get("tags", []),
            category=data.get("category", "general"),
            current_version=int(data.get("current_version", 1)),
            created_at=float(data.get("created_at", time.time())),
            published_at=float(data["published_at"]) if "published_at" in data else None,
        )
    
    def stats(self) -> dict:
        """Registry statistics."""
        return {
            "total_templates": len(self._templates),
            "published": sum(1 for t in self._templates.values() if t.is_published),
            "draft": sum(1 for t in self._templates.values() if t.status == TemplateStatus.DRAFT),
            "deprecated": sum(1 for t in self._templates.values() if t.status == TemplateStatus.DEPRECATED),
            "archived": sum(1 for t in self._templates.values() if t.status == TemplateStatus.ARCHIVED),
            "total_renders": self._render_count,
            "audit_records": len(self._audit_log),
        }


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_registry: Optional[PromptRegistry] = None


def get_prompt_registry(prompts_dir: Optional[Path] = None) -> PromptRegistry:
    """Get or create the global prompt registry."""
    global _registry
    if _registry is None:
        _registry = PromptRegistry(prompts_dir)
        _registry.ensure_builtins()
    return _registry
