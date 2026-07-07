"""meshctx knowledge_transfer — real implementation"""


class KnowledgeTransferEngine:
    """Cross-project knowledge transfer engine.

    Learns patterns from one project and suggests them for another.
    """

    def __init__(self):
        self._records = []
        self._knowledge = {}  # project_name → list of (topic, detail)

    def learn(self, project, topic, detail):
        """Learn a knowledge pattern from a project."""
        if project not in self._knowledge:
            self._knowledge[project] = []
        self._knowledge[project].append({"topic": topic, "detail": detail})

    def suggest(self, project):
        """Suggest knowledge patterns for a project based on what others know."""
        suggestions = []
        for src_project, items in self._knowledge.items():
            if src_project != project:
                for item in items:
                    suggestions.append(
                        f"From {src_project}: {item['topic']} — {item['detail']}"
                    )
        return suggestions

    def transfer(self, source, target, pattern):
        """Record a knowledge transfer from source project to target project."""
        self._records.append({
            "source": source,
            "target": target,
            "pattern": pattern,
        })


_engine = None


def get_knowledge_transfer():
    """Get the singleton KnowledgeTransferEngine instance."""
    global _engine
    if _engine is None:
        _engine = KnowledgeTransferEngine()
    return _engine
