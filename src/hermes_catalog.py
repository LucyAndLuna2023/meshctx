"""
MeshCtx Capability Catalog — Hermes 能力目录

完整注册 Hermes Agent 的全部能力：
- 80+ Skills（按类别组织，含描述/标签/依赖/使用场景）
- 30+ Tools（按 toolset 组织，含功能/参数/环境要求）
- 20+ Providers（模型供应商）
- 15+ Platforms（消息平台集成）

用法:
    from src.capabilities import CapabilityCatalog
    cat = CapabilityCatalog()
    
    # 按意图搜索技能
    skills = cat.find_skills("debug a python bug")
    
    # 按标签筛选
    dev_skills = cat.get_by_tag("testing")
    
    # 获取技能详情
    info = cat.skill_info("systematic-debugging")
"""

from typing import Optional
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class SkillEntry:
    name: str
    category: str
    description: str
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)  # 触发关键词
    requires_env: list[str] = field(default_factory=list)
    requires_commands: list[str] = field(default_factory=list)

@dataclass
class ToolEntry:
    name: str
    toolset: str
    description: str
    requires_env: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)

@dataclass
class ProviderEntry:
    name: str
    env_var: str
    type: str  # api_key | oauth | token


# ═══════════════════════════════════════════════════════════════════════
# Full Capability Catalog
# ═══════════════════════════════════════════════════════════════════════

SKILLS: dict[str, SkillEntry] = {
    # ── autonomous-ai-agents ──────────────────────────────────────
    "hermes-agent": SkillEntry(
        "hermes-agent", "autonomous-ai-agents",
        "Configure, extend, or contribute to Hermes Agent. Setup, multi-agent spawning, gateway, CLI.",
        ["hermes", "setup", "configuration", "multi-agent", "spawning", "cli", "gateway"],
        ["claude-code", "codex", "opencode"],
        ["hermes setup", "hermes config", "hermes gateway", "agent framework"],
    ),
    "claude-code": SkillEntry(
        "claude-code", "autonomous-ai-agents",
        "Delegate coding to Claude Code CLI (features, PRs).",
        ["delegation", "coding", "claude"],
        ["subagent-driven-development"],
        ["delegate to claude", "claude code"],
    ),
    "codex": SkillEntry(
        "codex", "autonomous-ai-agents",
        "Delegate coding to OpenAI Codex CLI (features, PRs).",
        ["delegation", "coding", "openai"],
        ["subagent-driven-development"],
        ["delegate to codex", "openai codex"],
    ),
    "opencode": SkillEntry(
        "opencode", "autonomous-ai-agents",
        "Delegate coding to OpenCode CLI (features, PR review).",
        ["delegation", "coding", "review"],
        ["subagent-driven-development"],
        ["opencode", "code review"],
    ),

    # ── creative ──────────────────────────────────────────────────
    "architecture-diagram": SkillEntry(
        "architecture-diagram", "creative",
        "Dark-themed SVG architecture/cloud/infra diagrams as HTML.",
        ["diagram", "architecture", "svg", "cloud", "visualization"],
        [], ["architecture diagram", "system diagram", "cloud diagram"],
    ),
    "ascii-art": SkillEntry(
        "ascii-art", "creative",
        "ASCII art: pyfiglet, cowsay, boxes, image-to-ascii.",
        ["ascii", "art", "terminal", "text"],
        [], ["ascii art", "text art", "banner"],
    ),
    "excalidraw": SkillEntry(
        "excalidraw", "creative",
        "Hand-drawn Excalidraw JSON diagrams (arch, flow, seq).",
        ["diagram", "hand-drawn", "architecture", "flow"],
        [], ["excalidraw", "hand drawn diagram", "sketch"],
    ),
    "baoyu-comic": SkillEntry(
        "baoyu-comic", "creative",
        "Knowledge comics (知识漫画): educational, biography, tutorial.",
        ["comic", "education", "visual", "chinese"],
        [], ["知识漫画", "comic", "educational comic"],
    ),
    "baoyu-infographic": SkillEntry(
        "baoyu-infographic", "creative",
        "Infographics: 21 layouts x 21 styles (信息图, 可视化).",
        ["infographic", "visualization", "data"],
        [], ["infographic", "信息图", "visualization"],
    ),
    "humanizer": SkillEntry(
        "humanizer", "creative",
        "Humanize text: strip AI-isms and add real voice.",
        ["writing", "editing", "tone"],
        [], ["humanize", "rewrite naturally", "make sound human"],
    ),
    "ideation": SkillEntry(
        "ideation", "creative",
        "Generate project ideas via creative constraints.",
        ["brainstorming", "creativity", "ideas"],
        [], ["idea generation", "brainstorm", "creative ideas"],
    ),

    # ── software-development ─────────────────────────────────────
    "plan": SkillEntry(
        "plan", "software-development",
        "Plan mode: write markdown plan to .hermes/plans/, no exec.",
        ["planning", "plan-mode", "implementation", "workflow"],
        ["writing-plans"],
        ["plan", "make a plan", "plan mode", "/plan"],
    ),
    "writing-plans": SkillEntry(
        "writing-plans", "software-development",
        "Write implementation plans: bite-sized tasks, paths, code. TDD-first, DRY, YAGNI.",
        ["planning", "design", "implementation", "documentation"],
        ["subagent-driven-development", "test-driven-development"],
        ["write a plan", "implementation plan", "task breakdown"],
    ),
    "subagent-driven-development": SkillEntry(
        "subagent-driven-development", "software-development",
        "Execute plans via delegate_task subagents (2-stage review).",
        ["delegation", "subagent", "implementation", "parallel"],
        ["writing-plans", "requesting-code-review", "test-driven-development"],
        ["execute plan", "delegate tasks", "parallel work", "subagent"],
    ),
    "test-driven-development": SkillEntry(
        "test-driven-development", "software-development",
        "TDD: enforce RED-GREEN-REFACTOR, tests before code.",
        ["testing", "tdd", "quality", "red-green-refactor"],
        ["systematic-debugging", "writing-plans"],
        ["tdd", "test driven", "write test first", "red green refactor"],
    ),
    "systematic-debugging": SkillEntry(
        "systematic-debugging", "software-development",
        "4-phase root cause debugging: understand bugs before fixing.",
        ["debugging", "troubleshooting", "root-cause", "investigation"],
        ["test-driven-development", "writing-plans"],
        ["debug", "bug", "error", "fix issue", "troubleshoot"],
    ),
    "python-test-framework-setup": SkillEntry(
        "python-test-framework-setup", "software-development",
        "Set up complete test framework for Python projects.",
        ["testing", "python", "framework", "setup", "quality"],
        ["test-driven-development", "writing-plans"],
        ["set up tests", "test framework", "testing setup"],
    ),
    "requesting-code-review": SkillEntry(
        "requesting-code-review", "software-development",
        "Pre-commit review: security scan, quality gates, auto-fix.",
        ["review", "security", "quality", "pre-commit"],
        ["subagent-driven-development"],
        ["code review", "review my code", "check code quality"],
    ),
    "python-debugpy": SkillEntry(
        "python-debugpy", "software-development",
        "Debug Python: pdb REPL + debugpy remote (DAP).",
        ["debugging", "python", "pdb", "dap"],
        ["systematic-debugging"],
        ["python debug", "pdb", "debugpy", "attach debugger"],
    ),
    "codebase-inspection": SkillEntry(
        "codebase-inspection", "software-development",
        "Inspect codebases w/ pygount: LOC, languages, ratios.",
        ["codebase", "analysis", "metrics", "statistics"],
        [], ["codebase stats", "lines of code", "project analysis"],
    ),
    "hermes-agent-skill-authoring": SkillEntry(
        "hermes-agent-skill-authoring", "software-development",
        "Author in-repo SKILL.md: frontmatter, validator, structure.",
        ["skills", "authoring", "documentation"],
        [], ["create skill", "write skill", "skill authoring"],
    ),

    # ── github ────────────────────────────────────────────────────
    "github-auth": SkillEntry(
        "github-auth", "github",
        "GitHub auth setup: HTTPS tokens, SSH keys, gh CLI login.",
        ["github", "auth", "ssh", "token", "setup"],
        [], ["github login", "gh auth", "github setup"],
    ),
    "github-pr-workflow": SkillEntry(
        "github-pr-workflow", "github",
        "GitHub PR lifecycle: branch, commit, open, CI, merge.",
        ["github", "pr", "workflow", "branch", "commit"],
        ["subagent-driven-development"],
        ["create pr", "pull request", "merge request"],
    ),
    "github-code-review": SkillEntry(
        "github-code-review", "github",
        "Review PRs: diffs, inline comments via gh or REST.",
        ["github", "review", "pr", "diff"],
        ["requesting-code-review"],
        ["review pr", "pr review"],
    ),
    "github-issues": SkillEntry(
        "github-issues", "github",
        "Create, triage, label, assign GitHub issues via gh or REST.",
        ["github", "issues", "triage", "label"],
        [], ["create issue", "github issue"],
    ),
    "github-repo-management": SkillEntry(
        "github-repo-management", "github",
        "Clone/create/fork repos; manage remotes, releases.",
        ["github", "repo", "clone", "fork", "remote"],
        [], ["clone repo", "fork repo", "create repo"],
    ),

    # ── mlops ─────────────────────────────────────────────────────
    "llama-cpp": SkillEntry(
        "llama-cpp", "mlops",
        "llama.cpp local GGUF inference + HF Hub model discovery.",
        ["llm", "inference", "local", "gguf"],
        ["huggingface-hub"],
        ["local llm", "llama", "gguf", "run model locally"],
    ),
    "huggingface-hub": SkillEntry(
        "huggingface-hub", "mlops",
        "HuggingFace hf CLI: search/download/upload models, datasets.",
        ["huggingface", "models", "datasets", "cli"],
        [], ["huggingface", "download model", "upload model"],
    ),
    "axolotl": SkillEntry(
        "axolotl", "mlops",
        "Axolotl: YAML LLM fine-tuning (LoRA, DPO, GRPO).",
        ["fine-tuning", "lora", "dpo", "training"],
        ["unsloth"],
        ["finetune", "lora", "train model"],
    ),
    "unsloth": SkillEntry(
        "unsloth", "mlops",
        "Unsloth: 2-5x faster LoRA/QLoRA fine-tuning, less VRAM.",
        ["fine-tuning", "lora", "efficiency", "training"],
        ["axolotl"],
        ["unsloth", "fast finetune", "efficient training"],
    ),
    "serving-llms-vllm": SkillEntry(
        "serving-llms-vllm", "mlops",
        "vLLM: high-throughput LLM serving, OpenAI API, quantization.",
        ["serving", "inference", "api", "quantization"],
        [], ["vllm", "serve model", "llm api"],
    ),
    "dspy": SkillEntry(
        "dspy", "mlops",
        "DSPy: declarative LM programs, auto-optimize prompts, RAG.",
        ["prompting", "optimization", "rag", "declarative"],
        [], ["dspy", "optimize prompts", "rag pipeline"],
    ),
    "evaluating-llms-harness": SkillEntry(
        "evaluating-llms-harness", "mlops",
        "lm-eval-harness: benchmark LLMs (MMLU, GSM8K, etc.).",
        ["evaluation", "benchmark", "testing"],
        [], ["evaluate model", "benchmark", "mmlu"],
    ),

    # ── productivity ─────────────────────────────────────────────
    "notion": SkillEntry(
        "notion", "productivity",
        "Notion API via curl: pages, databases, blocks, search.",
        ["notion", "api", "notes", "database"],
        [], ["notion", "notion api"],
        ["NOTION_API_KEY"],
    ),
    "linear": SkillEntry(
        "linear", "productivity",
        "Linear: manage issues, projects, teams via GraphQL + curl.",
        ["linear", "issues", "project-management", "graphql"],
        [], ["linear", "linear issues"],
        ["LINEAR_API_KEY"],
    ),
    "google-workspace": SkillEntry(
        "google-workspace", "productivity",
        "Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python.",
        ["google", "gmail", "calendar", "drive", "docs"],
        [], ["gmail", "google calendar", "google drive", "google docs"],
    ),
    "airtable": SkillEntry(
        "airtable", "productivity",
        "Airtable REST API via curl. Records CRUD, filters, upserts.",
        ["airtable", "database", "api", "spreadsheet"],
        [], ["airtable", "airtable api"],
        ["AIRTABLE_API_KEY"],
    ),
    "ocr-and-documents": SkillEntry(
        "ocr-and-documents", "productivity",
        "Extract text from PDFs/scans (pymupdf, marker-pdf).",
        ["ocr", "pdf", "documents", "extraction"],
        [], ["extract text from pdf", "ocr", "scan document"],
    ),

    # ── research ─────────────────────────────────────────────────
    "arxiv": SkillEntry(
        "arxiv", "research",
        "Search arXiv papers by keyword, author, category, or ID.",
        ["research", "papers", "academic", "search"],
        [], ["arxiv", "research paper", "academic search"],
    ),
    "polymarket": SkillEntry(
        "polymarket", "research",
        "Query Polymarket: markets, prices, orderbooks, history.",
        ["market", "prediction", "prices", "finance"],
        [], ["polymarket", "prediction market"],
    ),
    "blogwatcher": SkillEntry(
        "blogwatcher", "research",
        "Monitor blogs and RSS/Atom feeds via blogwatcher-cli tool.",
        ["rss", "monitoring", "blog", "feed"],
        [], ["monitor blogs", "rss feed", "blog watcher"],
    ),

    # ── social-media ─────────────────────────────────────────────
    "xurl": SkillEntry(
        "xurl", "social-media",
        "X/Twitter via xurl CLI: post, search, DM, media, v2 API.",
        ["twitter", "social", "post", "search"],
        [], ["twitter", "x", "tweet", "post to x"],
    ),

    # ── mcp ──────────────────────────────────────────────────────
    "native-mcp": SkillEntry(
        "native-mcp", "mcp",
        "MCP client: connect servers, register tools (stdio/HTTP).",
        ["mcp", "tools", "integrations", "protocol"],
        [], ["mcp", "mcp server", "connect mcp", "model context protocol"],
    ),

    # ── email ────────────────────────────────────────────────────
    "himalaya": SkillEntry(
        "himalaya", "email",
        "Himalaya CLI: IMAP/SMTP email from terminal.",
        ["email", "imap", "smtp", "terminal"],
        [], ["send email", "read email", "check inbox"],
    ),

    # ── media ────────────────────────────────────────────────────
    "youtube-content": SkillEntry(
        "youtube-content", "media",
        "YouTube transcripts to summaries, threads, blogs.",
        ["youtube", "transcript", "summary", "content"],
        [], ["youtube transcript", "summarize video"],
    ),
    "spotify": SkillEntry(
        "spotify", "media",
        "Spotify: play, search, queue, manage playlists and devices.",
        ["spotify", "music", "playlist", "audio"],
        [], ["spotify", "play music", "spotify playlist"],
    ),

    # ── devops ───────────────────────────────────────────────────
    "webhook-subscriptions": SkillEntry(
        "webhook-subscriptions", "devops",
        "Webhook subscriptions: event-driven agent runs.",
        ["webhook", "events", "automation", "trigger"],
        [], ["webhook", "event trigger"],
    ),

    # ── note-taking ──────────────────────────────────────────────
    "obsidian": SkillEntry(
        "obsidian", "note-taking",
        "Read, search, and create notes in the Obsidian vault.",
        ["obsidian", "notes", "markdown", "knowledge"],
        [], ["obsidian", "vault", "my notes"],
    ),

    # ── smart-home ───────────────────────────────────────────────
    "openhue": SkillEntry(
        "openhue", "smart-home",
        "Control Philips Hue lights, scenes, rooms via OpenHue CLI.",
        ["home", "lights", "hue", "automation"],
        [], ["turn on lights", "hue lights", "smart home"],
    ),

    # ── data-science ─────────────────────────────────────────────
    "jupyter-live-kernel": SkillEntry(
        "jupyter-live-kernel", "data-science",
        "Iterative Python via live Jupyter kernel (hamelnb).",
        ["jupyter", "python", "data", "notebook"],
        [], ["jupyter", "notebook", "data analysis"],
    ),

    # ── red-teaming ──────────────────────────────────────────────
    "godmode": SkillEntry(
        "godmode", "red-teaming",
        "Jailbreak LLMs: Parseltongue, GODMODE, ULTRAPLINIAN.",
        ["jailbreak", "security", "testing", "red-team"],
        [], ["jailbreak", "godmode", "red team"],
    ),

    # ── mlops/models ─────────────────────────────────────────────
    "segment-anything-model": SkillEntry(
        "segment-anything-model", "mlops",
        "SAM: zero-shot image segmentation via points, boxes, masks.",
        ["computer-vision", "segmentation", "images"],
        [], ["segment image", "sam", "image segmentation"],
    ),
    "audiocraft-audio-generation": SkillEntry(
        "audiocraft-audio-generation", "mlops",
        "AudioCraft: MusicGen text-to-music, AudioGen text-to-sound.",
        ["audio", "music", "generation"],
        [], ["generate music", "musicgen", "text to audio"],
    ),

    # ── dogfood ──────────────────────────────────────────────────
    "dogfood": SkillEntry(
        "dogfood", "dogfood",
        "Exploratory QA of web apps: find bugs, evidence, reports.",
        ["qa", "testing", "web", "browser"],
        [], ["qa", "test web app", "find bugs"],
    ),

    # ── yuanbao ──────────────────────────────────────────────────
    "yuanbao": SkillEntry(
        "yuanbao", "yuanbao",
        "Yuanbao (元宝) groups: @mention users, query info/members.",
        ["yuanbao", "messaging", "chinese"],
        [], ["元宝", "yuanbao", "元宝群"],
    ),
}

# ── Hermes Tools ───────────────────────────────────────────────────
TOOLS: dict[str, ToolEntry] = {
    "read_file": ToolEntry("read_file", "file", "Read text file with line numbers and pagination.", [], ["read file", "cat", "view file"]),
    "write_file": ToolEntry("write_file", "file", "Write content to file, overwriting existing.", [], ["write file", "create file", "save file"]),
    "search_files": ToolEntry("search_files", "file", "Search file contents or find files by name (ripgrep).", [], ["search", "grep", "find files"]),
    "patch": ToolEntry("patch", "file", "Targeted find-and-replace edits in files.", [], ["edit file", "replace text", "patch file"]),
    "terminal": ToolEntry("terminal", "terminal", "Execute shell commands (foreground/background/PTY).", [], ["run command", "shell", "execute"]),
    "process": ToolEntry("process", "terminal", "Manage background processes (poll/wait/kill/write).", [], ["background process", "process status"]),
    "browser_navigate": ToolEntry("browser_navigate", "browser", "Navigate to URL and get page snapshot.", [], ["open browser", "navigate to", "go to url"]),
    "browser_snapshot": ToolEntry("browser_snapshot", "browser", "Get accessibility tree snapshot of current page.", [], ["page snapshot", "what's on page"]),
    "browser_click": ToolEntry("browser_click", "browser", "Click element by ref ID from snapshot.", [], ["click", "press button"]),
    "browser_type": ToolEntry("browser_type", "browser", "Type text into input field.", [], ["type in", "fill form", "enter text"]),
    "vision_analyze": ToolEntry("vision_analyze", "vision", "Inspect image from URL/file path with vision AI.", [], ["look at image", "analyze picture", "what's in this image"]),
    "web_search": ToolEntry("web_search", "web", "Search the web via API.", [], ["search web", "google", "look up"]),
    "web_extract": ToolEntry("web_extract", "web", "Extract content from URL.", [], ["extract page", "read url content"]),
    "memory": ToolEntry("memory", "memory", "Save durable info to persistent memory across sessions.", [], ["remember", "save for later", "don't forget"]),
    "session_search": ToolEntry("session_search", "session_search", "Search past conversations and browse recent sessions.", [], ["past conversation", "what did we do", "previous session"]),
    "delegate_task": ToolEntry("delegate_task", "delegation", "Spawn subagent for isolated task execution.", [], ["delegate", "spawn agent", "parallel task"]),
    "cronjob": ToolEntry("cronjob", "cronjob", "Manage scheduled cron jobs (create/list/pause/remove).", [], ["schedule", "cron", "automated task"]),
    "todo": ToolEntry("todo", "todo", "Manage in-session task list with status tracking.", [], ["todo", "task list", "what's next"]),
    "clarify": ToolEntry("clarify", "clarify", "Ask user clarifying questions with multiple choice.", [], ["ask", "question", "clarify"]),
    "execute_code": ToolEntry("execute_code", "code_execution", "Run Python script that can call Hermes tools programmatically.", [], ["run python", "execute script"]),
    "skill_view": ToolEntry("skill_view", "skills", "Load skill's full content or access linked files.", [], ["load skill", "view skill", "skill details"]),
    "skill_manage": ToolEntry("skill_manage", "skills", "Manage skills (create/update/delete/patch).", [], ["create skill", "update skill", "save skill"]),
}

# ── Providers ─────────────────────────────────────────────────────
PROVIDERS: dict[str, ProviderEntry] = {
    "openrouter": ProviderEntry("openrouter", "OPENROUTER_API_KEY", "api_key"),
    "anthropic": ProviderEntry("anthropic", "ANTHROPIC_API_KEY", "api_key"),
    "openai": ProviderEntry("openai", "OPENAI_API_KEY", "api_key"),
    "deepseek": ProviderEntry("deepseek", "DEEPSEEK_API_KEY", "api_key"),
    "google": ProviderEntry("google", "GOOGLE_API_KEY", "api_key"),
    "xai": ProviderEntry("xai", "XAI_API_KEY", "api_key"),
    "huggingface": ProviderEntry("huggingface", "HF_TOKEN", "token"),
    "alibaba": ProviderEntry("alibaba", "DASHSCOPE_API_KEY", "api_key"),
    "moonshot": ProviderEntry("moonshot", "KIMI_API_KEY", "api_key"),
    "minimax": ProviderEntry("minimax", "MINIMAX_API_KEY", "api_key"),
    "zhipu": ProviderEntry("zhipu", "GLM_API_KEY", "api_key"),
    "nous": ProviderEntry("nous", "", "oauth"),
    "github_copilot": ProviderEntry("github_copilot", "COPILOT_GITHUB_TOKEN", "token"),
}

# ── Platforms ─────────────────────────────────────────────────────
PLATFORMS = [
    "CLI", "Telegram", "Discord", "Slack", "WhatsApp", "Signal",
    "Email", "SMS", "Matrix", "Mattermost", "Home Assistant",
    "DingTalk", "Feishu", "WeCom", "WeChat", "API Server", "Webhooks",
]


# ═══════════════════════════════════════════════════════════════════════
# Capability Catalog
# ═══════════════════════════════════════════════════════════════════════

class CapabilityCatalog:
    """Hermes 能力目录 — 技能发现、工具查询、供应商管理。"""

    def __init__(self):
        self.skills: dict[str, SkillEntry] = SKILLS
        self.tools: dict[str, ToolEntry] = TOOLS
        self.providers: dict[str, ProviderEntry] = PROVIDERS
        self.platforms: list[str] = PLATFORMS

    # ── 技能查询 ──────────────────────────────────────────────────

    def list_categories(self) -> list[str]:
        """列出所有技能类别。"""
        return sorted(set(s.category for s in self.skills.values()))

    def get_by_category(self, category: str) -> list[SkillEntry]:
        """获取某类别下的所有技能。"""
        return [s for s in self.skills.values() if s.category == category]

    def get_by_tag(self, tag: str) -> list[SkillEntry]:
        """按标签搜索技能。"""
        tag_lower = tag.lower()
        return [s for s in self.skills.values() if tag_lower in [t.lower() for t in s.tags]]

    def find_skills(self, query: str, top_k: int = 10) -> list[tuple[SkillEntry, float]]:
        """基于关键词匹配搜索技能。返回 (SkillEntry, score)。"""
        query_lower = query.lower()
        query_words = set(query_lower.split())
        scored = []

        for skill in self.skills.values():
            score = 0.0
            search_text = (
                skill.name + " " + skill.description + " " +
                " ".join(skill.tags) + " ".join(skill.triggers)
            ).lower()

            # 精确触发词匹配 — 最高权重
            for trigger in skill.triggers:
                if trigger.lower() in query_lower:
                    score += 5.0
            # 名称匹配
            if skill.name.lower() in query_lower:
                score += 4.0
            # 词匹配
            for word in query_words:
                if word in search_text:
                    score += 1.0
            if score > 0:
                scored.append((skill, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def skill_info(self, name: str) -> Optional[SkillEntry]:
        """获取技能详情。"""
        return self.skills.get(name)

    # ── 工具查询 ──────────────────────────────────────────────────

    def find_tools(self, query: str, top_k: int = 10) -> list[tuple[ToolEntry, float]]:
        """搜索工具。"""
        query_lower = query.lower()
        scored = []
        for tool in self.tools.values():
            score = 0.0
            if tool.name in query_lower:
                score += 5.0
            for trigger in tool.triggers:
                if trigger.lower() in query_lower:
                    score += 3.0
            if query_lower in tool.description.lower():
                score += 1.0
            if score > 0:
                scored.append((tool, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # ── 统计 ──────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "skills_total": len(self.skills),
            "categories": len(self.list_categories()),
            "tools_total": len(self.tools),
            "providers": len(self.providers),
            "platforms": len(self.platforms),
        }

    def export_skill_index(self) -> list[dict]:
        """导出技能索引（供前端/API使用）。"""
        return [
            {
                "name": s.name,
                "category": s.category,
                "description": s.description,
                "tags": s.tags,
                "related": s.related,
            }
            for s in sorted(self.skills.values(), key=lambda x: x.name)
        ]


# 全局单例
_catalog: Optional[CapabilityCatalog] = None

def get_catalog() -> CapabilityCatalog:
    global _catalog
    if _catalog is None:
        _catalog = CapabilityCatalog()
    return _catalog
