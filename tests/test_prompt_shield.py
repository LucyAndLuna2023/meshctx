"""prompt_shield 注入检测测试"""
import pytest

class TestJailbreakDetection:
    def test_ignore_previous_instructions(self):
        pytest.skip('TODO: JAIL-001 ignore all previous instructions')

    def test_dan_mode(self):
        pytest.skip('TODO: JAIL-002 DAN mode detection')

    def test_reveal_system_prompt(self):
        pytest.skip('TODO: JAIL-003 system prompt extraction')

    def test_output_prompt_verbatim(self):
        pytest.skip('TODO: JAIL-004 output verbatim')

    def test_translation_jailbreak(self):
        pytest.skip('TODO: JAIL-005 translation jailbreak')


class TestSQLInjection:
    def test_classic_tautology(self):
        pytest.skip('TODO: SQLI-001 tautology detection')

    def test_union_select(self):
        pytest.skip('TODO: SQLI-002 UNION SELECT')

    def test_statement_chaining(self):
        pytest.skip('TODO: SQLI-003 statement chaining')


class TestFalsePositives:
    def test_normal_text_passes(self):
        pytest.skip('TODO: normal text should pass')

    def test_code_discussion_passes(self):
        pytest.skip('TODO: discussing SQL should not trigger')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
