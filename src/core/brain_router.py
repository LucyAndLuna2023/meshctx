"""meshctx brain_router — 智能任务路由 (v3.115.36)

Real routing based on task type analysis, not random numbers.
Routes queries to optimal model based on task category, complexity, and cost."""

import re
from typing import Dict, List, Optional, Tuple


# ── Task type detection ──────────────────────────────────────

TASK_PATTERNS = {
    "code": [
        r"(写|编写|生成|创建|帮我写).{0,10}(代码|程序|脚本|函数|类|class|def|function|模块|算法|组件|插件|plugin)",
        r"(修|改|修复|debug|调试|重构|优化).{0,5}(代码|bug|错误|问题)",
        r"(code|python|javascript|java|rust|go|c\+\+|编程|import\s|from\s+\w+\s+import|pip\s|npm\s|git\s|api\s)",
        r"(git|commit|push|pull|merge|branch|repo|github|PR|pull request)",
        r"(api|endpoint|route|controller|middleware|数据库|database|sql|query|docker|k8s|部署)",
    ],
    "analysis": [
        r"(分析|计算|统计|评估|审查|检查|审计|review|audit|analy)",
        r"(数据|指标|性能|performance|benchmark|比较|对比|compare)",
        r"(多少钱|价格|成本|cost|利润|收入|revenue)",
        r"(报告|report|总结|summary|结论|conclusion)",
    ],
    "creative": [
        r"(写|创作|生成).{0,12}(文章|故事|诗歌|诗|blog|post|小说|剧本|文案|歌词|作曲)",
        r"(翻译|translate|改写|rewrite|润色|polish)",
        r"(创意|想法|idea|灵感|设计|design|头脑风暴|brainstorm)",
    ],
    "search": [
        r"(搜索|查询|查找|找|查|search|find|lookup|什么是|什么是|谁|where|when|how)",
        r"(最新|新闻|news|今天|today|现在|当前|current|实时)",
        r"(股价|股票|天气|汇率|price|stock|weather)",
    ],
    "chat": [
        r"(你好|hi|hello|hey|谢谢|thanks|再见|bye|晚安|早安)",
        r"(怎么样|如何|how are|what's up|聊天|闲聊|talk|chat)",
    ],
}


def classify_task(text: str) -> Tuple[str, float]:
    """Classify task type from user message. Returns (category, confidence)."""
    text_lower = text.lower().strip()
    scores = {}
    for category, patterns in TASK_PATTERNS.items():
        score = 0.0
        for pat in patterns:
            if re.search(pat, text_lower):
                score += 1.0
        if score > 0:
            scores[category] = min(score / len(patterns), 1.0)
    
    if not scores:
        return ("chat", 0.5)
    
    # Conflict resolution: creative > code (写诗 ≠ 写代码)
    if "creative" in scores and "code" in scores:
        if not re.search(r"(代码|程序|函数|脚本|class|def|function|module|api)", text_lower):
            del scores["code"]
    
    best = max(scores, key=scores.get)
    return (best, scores[best])


def estimate_complexity(text: str) -> float:
    """Estimate task complexity 0-1 from message length and structure."""
    score = 0.0
    # Length factor
    length = len(text)
    if length > 500:
        score += 0.3
    elif length > 200:
        score += 0.2
    elif length > 50:
        score += 0.1
    
    # Code indicators
    if re.search(r"(class|def|function|import|async|await)", text):
        score += 0.2
    if re.search(r"(多文件|multi.?file|架构|architecture|重构|refactor)", text):
        score += 0.2
    
    # Multiple requirements
    if len(re.findall(r"(\d+\.|[-*]\s|第[一二三])", text)) > 2:
        score += 0.15
    
    return min(score, 1.0)


# ── Model routing ────────────────────────────────────────────

MODEL_ROUTES = {
    "code": {
        "fast": "deepseek:v4-flash",
        "balanced": "deepseek:v4-flash",
        "powerful": "deepseek:v4-pro",
    },
    "analysis": {
        "fast": "deepseek:v4-flash",
        "balanced": "deepseek:v4-pro",
        "powerful": "deepseek:v4-pro",
    },
    "creative": {
        "fast": "deepseek:v4-flash",
        "balanced": "deepseek:v4-pro",
        "powerful": "deepseek:v4-pro",
    },
    "search": {
        "fast": "deepseek:v4-flash",
        "balanced": "deepseek:v4-flash",
        "powerful": "deepseek:v4-flash",
    },
    "chat": {
        "fast": "deepseek:v4-flash",
        "balanced": "deepseek:v4-flash",
        "powerful": "deepseek:v4-pro",
    },
}

# Cost estimates (tokens per $)
MODEL_COST = {
    "deepseek:v4-flash": 0.5,
    "deepseek:v4-flash": 1.0,
    "deepseek:v4-pro": 2.0,
}


class SmartRouter:
    """Intelligent model router — task-based, cost-aware."""

    def __init__(self):
        self._route_history: List[Dict] = []
        self._cost_saved = 0.0

    def route(self, text: str, preference: str = "balanced") -> Dict:
        """Route a user message to the best model.

        Args:
            text: user message
            preference: "fast", "balanced", or "powerful"

        Returns dict with: model, task_type, confidence, complexity, reason
        """
        task_type, confidence = classify_task(text)
        complexity = estimate_complexity(text)

        # Adjust preference based on complexity
        if complexity > 0.6 and preference == "fast":
            preference = "balanced"  # complex tasks need better models
        elif complexity > 0.8:
            preference = "powerful"

        routes = MODEL_ROUTES.get(task_type, MODEL_ROUTES["chat"])
        model = routes.get(preference, routes["balanced"])

        # Calculate cost estimate
        cost = MODEL_COST.get(model, 1.0)

        result = {
            "model": model,
            "task_type": task_type,
            "confidence": round(confidence, 2),
            "complexity": round(complexity, 2),
            "preference": preference,
            "estimated_cost": cost,
            "reason": (
                f"Task={task_type}({confidence:.0%}), "
                f"complexity={complexity:.0%}, "
                f"mode={preference} → {model}"
            ),
        }

        # Track cost savings vs always using v4-pro
        baseline_cost = MODEL_COST.get("deepseek:v4-pro", 2.0)
        self._cost_saved += baseline_cost - cost
        self._route_history.append(result)
        if len(self._route_history) > 100:
            self._route_history = self._route_history[-50:]

        return result

    def stats(self) -> Dict:
        """Router statistics."""
        if not self._route_history:
            return {"routes": 0, "cost_saved": 0}
        model_counts = {}
        for r in self._route_history:
            m = r["model"]
            model_counts[m] = model_counts.get(m, 0) + 1
        return {
            "routes": len(self._route_history),
            "cost_saved": round(self._cost_saved, 2),
            "model_distribution": model_counts,
            "last_route": self._route_history[-1] if self._route_history else None,
        }

    def list_models(self) -> List[Dict]:
        """List available models with costs."""
        return [
            {"id": mid, "cost_level": cost}
            for mid, cost in MODEL_COST.items()
        ]


# ── Singleton ────────────────────────────────────────────────

_router: Optional[SmartRouter] = None


def get_router() -> SmartRouter:
    global _router
    if _router is None:
        _router = SmartRouter()
    return _router
