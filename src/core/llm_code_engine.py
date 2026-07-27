"""meshctx LLM 增强代码引擎 v1 — refactor + PR + review 全链路 AI 化

核心设计：
  1. 规则引擎做"发现"（AST 解析、diff 分析）
  2. LLM 做"决策"（重构建议、PR 描述、代码审查）
  3. 双引擎互补：规则引擎精确但僵硬，LLM 灵活但不稳定

对标记准：
  - refactor_agent.py: AST 发现 → LLM 建议 → 人工确认 → 自动应用
  - pr_agent.py: git diff → LLM 摘要 → 多模板 PR → reviewer 推荐
"""
import os, re, json, subprocess
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from pathlib import Path


# ═══════════════════════════════════════════════════
# LLM 增强重构引擎
# ═══════════════════════════════════════════════════

@dataclass
class RefactorSuggestion:
    """LLM 生成的重构建议"""
    title: str
    file: str
    line_range: str
    problem: str
    suggestion: str
    before_code: str = ""
    after_code: str = ""
    risk: str = "low"  # low/medium/high
    auto_applicable: bool = False

@dataclass
class LLMRefactorResult:
    suggestions: list[RefactorSuggestion]
    model_used: str
    tokens_used: int = 0
    latency_ms: float = 0.0

class LLMRefactorEngine:
    """LLM 增强重构引擎 — 规则发现 + LLM 建议"""

    def __init__(self, model_adapter=None):
        self.adapter = model_adapter

    def analyze_file(self, filepath: str, context: str = "") -> LLMRefactorResult:
        """分析单个文件，返回重构建议"""
        p = Path(filepath).expanduser()
        if not p.exists():
            return LLMRefactorResult(suggestions=[], model_used="none")

        code = p.read_text(errors="replace")
        # 截断过长代码
        if len(code) > 8000:
            code = code[:8000] + "\n... (truncated)"

        prompt = f"""Analyze the following code and suggest 3-5 specific refactoring improvements.
Focus on: readability, performance, security, DRY violations, error handling gaps.

File: {filepath}
Lines: {len(code.splitlines())}

```python
{code}
```

Return JSON array of suggestions:
[{{"title": "...", "line_range": "L10-L20", "problem": "...", "suggestion": "...", "risk": "low|medium|high"}}]

Reply with ONLY the JSON array, no other text."""

        if not self.adapter:
            return self._fallback_analyze(filepath, code)

        try:
            resp = self.adapter.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=1024
            )
            suggestions = self._parse_json(resp.content)
            return LLMRefactorResult(
                suggestions=[RefactorSuggestion(**s) for s in suggestions if s.get("title")],
                model_used=resp.model,
                tokens_used=resp.tokens_used,
            )
        except Exception as e:
            return self._fallback_analyze(filepath, code)

    def _parse_json(self, text: str) -> list:
        """安全解析 LLM 返回的 JSON"""
        # 去除 markdown 代码块
        text = re.sub(r'```(?:json)?\s*', '', text)
        text = re.sub(r'```', '', text)
        try:
            return json.loads(text)
    except Exception:
            # 尝试提取 JSON 数组
            m = re.search(r'\[.*\]', text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
    except Exception:
                    pass
        return []

    def _fallback_analyze(self, filepath: str, code: str) -> LLMRefactorResult:
        """无 LLM 时的规则引擎回退"""
        suggestions = []
        lines = code.splitlines()
        # 检查函数长度
        for i, line in enumerate(lines, 1):
            if line.strip().startswith("def ") and i > 0:
                # 找函数体结束
                body_start = i
                body_end = min(body_start + 50, len(lines))
                func_len = body_end - body_start
                if func_len > 30:
                    suggestions.append(RefactorSuggestion(
                        title="Overly long function",
                        file=filepath,
                        line_range=f"L{body_start}-L{body_end}",
                        problem=f"Function is {func_len} lines, exceeds 30-line recommendation",
                        suggestion="Consider extracting helper functions",
                        risk="low",
                    ))
                break  # 只检查第一个函数作为示例
        return LLMRefactorResult(suggestions=suggestions, model_used="rule_engine")

    def apply_suggestion(self, filepath: str, suggestion: RefactorSuggestion) -> bool:
        """自动应用低风险重构建议"""
        if suggestion.risk != "low" or not suggestion.auto_applicable:
            return False
        p = Path(filepath).expanduser()
        if not p.exists():
            return False
        content = p.read_text(errors="replace")
        if suggestion.before_code and suggestion.before_code in content:
            new_content = content.replace(suggestion.before_code, suggestion.after_code)
            p.write_text(new_content)
            return True
        return False


# ═══════════════════════════════════════════════════
# LLM 增强 PR 引擎
# ═══════════════════════════════════════════════════

@dataclass
class PRDescription:
    title: str
    summary: str
    changes: list[str]
    breaking: bool = False
    reviewer: str = ""

class LLMPREngine:
    """LLM 增强 PR 引擎 — git diff → LLM 摘要 → 多模板"""

    PR_TEMPLATES = {
        "feature": "✨ {title}\n\n## What\n{summary}\n\n## Changes\n{changes}\n\n## Testing\n- [ ] pytest passed\n- [ ] manual test",
        "bugfix": "🐛 {title}\n\n## Problem\n{summary}\n\n## Fix\n{changes}\n\n## Verification\n- [ ] bug reproduced and fixed",
        "docs": "📝 {title}\n\n## What changed\n{summary}\n\n## Files\n{changes}",
        "hotfix": "🚨 {title}\n\n## Urgency\nCRITICAL\n\n## Fix\n{summary}\n\n## Changes\n{changes}",
    }

    def __init__(self, model_adapter=None):
        self.adapter = model_adapter

    def generate_pr(self, pr_type: str = "feature", base: str = "main", head: str = "HEAD") -> PRDescription:
        """自动生成 PR 描述 — 从 git diff 到结构化 PR"""
        diff = self._get_diff(base, head)
        if not diff:
            return PRDescription(title="(no changes)", summary="", changes=[])

        if self.adapter and len(diff) < 4000:
            return self._llm_pr(pr_type, diff)
        return self._rule_pr(pr_type, diff)

    def _get_diff(self, base: str, head: str) -> str:
        import shlex
        try:
            r = subprocess.run(
                f"git diff {shlex.quote(base)}..{shlex.quote(head)} --stat && echo '---' && git diff {shlex.quote(base)}..{shlex.quote(head)} -- . ':(exclude)*.lock' ':(exclude)*.json'",
                shell=True, capture_output=True, text=True, timeout=20, executable='/bin/bash'
            )
            return r.stdout[:4000]
    except Exception:
            return ""

    def _llm_pr(self, pr_type: str, diff: str) -> PRDescription:
        prompt = f"""Generate a {pr_type} pull request description from this git diff:

```
{diff[:3000]}
```

Return JSON:
{{"title": "concise title", "summary": "1-2 paragraph description", "changes": ["- item1", "- item2"], "breaking": false, "reviewer": "who should review"}}

Reply with ONLY the JSON object."""
        try:
            resp = self.adapter.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=512
            )
            data = json.loads(re.sub(r'```(?:json)?\s*|```', '', resp.content).strip())
            return PRDescription(
                title=data.get("title", "Update"),
                summary=data.get("summary", ""),
                changes=data.get("changes", []),
                breaking=data.get("breaking", False),
                reviewer=data.get("reviewer", ""),
            )
    except Exception:
            return self._rule_pr(pr_type, diff)

    def _rule_pr(self, pr_type: str, diff: str) -> PRDescription:
        files = re.findall(r'\|\s+\d+', diff.split('---')[0]) if '---' in diff else []
        changes = [f"- Modified {f.strip()}" for f in files[:10]]
        return PRDescription(
            title=f"{pr_type}: code update ({len(changes)} files)",
            summary="Auto-generated from git diff (no LLM available)",
            changes=changes or ["- (see git diff)"],
        )

    def format_pr(self, pr: PRDescription, pr_type: str = "feature") -> str:
        template = self.PR_TEMPLATES.get(pr_type, self.PR_TEMPLATES["feature"])
        changes_str = "\n".join(pr.changes) if pr.changes else "- (no details)"
        return template.format(
            title=pr.title, summary=pr.summary, changes=changes_str
        )


# ═══════════════════════════════════════════════════
# LLM 代码审查引擎
# ═══════════════════════════════════════════════════

@dataclass
class ReviewComment:
    file: str
    line: int
    severity: str  # info/warning/error/critical
    message: str
    suggestion: str = ""

class LLMReviewEngine:
    """LLM 代码审查引擎 — diff → 结构化审查意见"""

    def __init__(self, model_adapter=None):
        self.adapter = model_adapter

    def review_diff(self, diff: str) -> list[ReviewComment]:
        if not diff.strip():
            return []
        if not self.adapter or len(diff) > 5000:
            return self._rule_review(diff)

        prompt = f"""Review this git diff and identify issues. Return JSON array:

```
{diff[:4000]}
```

Return:
[{{"file": "path", "line": 0, "severity": "warning|error|critical", "message": "...", "suggestion": "..."}}]

Focus on: bugs, security, performance, error handling, naming. Reply with ONLY JSON array."""
        try:
            resp = self.adapter.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=1024
            )
            data = json.loads(re.sub(r'```(?:json)?\s*|```', '', resp.content).strip())
            return [ReviewComment(**c) for c in data if c.get("message")]
    except Exception:
            return self._rule_review(diff)

    def _rule_review(self, diff: str) -> list[ReviewComment]:
        comments = []
        # 检测危险模式
        for i, line in enumerate(diff.splitlines(), 1):
            if "eval(" in line:
                comments.append(ReviewComment(file="unknown", line=i, severity="critical",
                    message="Use of eval() is dangerous", suggestion="Use ast.literal_eval or JSON parsing"))
            if "password" in line.lower() and ("=" in line or ":" in line):
                comments.append(ReviewComment(file="unknown", line=i, severity="error",
                    message="Possible hardcoded credential", suggestion="Use environment variables or secrets manager"))
            if "TODO" in line or "FIXME" in line:
                comments.append(ReviewComment(file="unknown", line=i, severity="info",
                    message="Unresolved TODO/FIXME", suggestion="Create a tracking issue"))
        return comments
