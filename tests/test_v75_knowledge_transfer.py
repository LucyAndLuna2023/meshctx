"""v3.75 Knowledge Transfer — tests"""
import pytest
from src.core.knowledge_transfer import KnowledgeTransferEngine, get_knowledge_transfer

class TestTransfer:
    def test_learn_suggest(self):
        e = KnowledgeTransferEngine()
        e.learn("project_a", "NSIS Var syntax", "one per line")
        suggestions = e.suggest("project_b")
        assert len(suggestions) > 0

    def test_transfer(self):
        e = KnowledgeTransferEngine()
        e.transfer("a", "b", "pattern")
        assert len(e._records) == 1

    def test_singleton(self):
        assert get_knowledge_transfer() is get_knowledge_transfer()
