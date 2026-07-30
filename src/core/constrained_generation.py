"""Constrained Generation — 结构化输出引擎 (v3.115.46)

Ensures LLM output conforms to specified formats (JSON, schema, patterns).
Post-hoc validation + retry, no model-level constrained decoding needed."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.constrained")


@dataclass
class ConstraintResult:
    """Result of constrained generation attempt."""
    output: str
    valid: bool
    parsed: Any = None
    errors: List[str] = field(default_factory=list)
    attempts: int = 1
    retries: int = 0


class JSONConstraint:
    """Ensure output is valid JSON, optionally matching a schema."""

    def __init__(self, schema: Dict = None, required_fields: List[str] = None):
        self.schema = schema or {}
        self.required_fields = required_fields or []

    def validate(self, text: str) -> Tuple[bool, Any, List[str]]:
        """Try to parse and validate JSON."""
        errors = []
        # Extract JSON from text (handle markdown code blocks)
        json_text = text
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            json_text = m.group(1)
        
        # Try to find JSON object/array
        m2 = re.search(r'(\{.*\}|\[.*\])', json_text, re.DOTALL)
        if m2:
            json_text = m2.group(1)

        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as e:
            return False, None, [f"JSON parse error: {e}"]

        # Check required fields
        if self.required_fields and isinstance(parsed, dict):
            for field in self.required_fields:
                if field not in parsed:
                    errors.append(f"Missing required field: {field}")

        # Basic schema validation
        if self.schema and isinstance(parsed, dict):
            for key, expected_type in self.schema.items():
                if key in parsed:
                    actual = type(parsed[key]).__name__
                    if actual != expected_type:
                        errors.append(
                            f"Field '{key}' expected {expected_type}, got {actual}"
                        )

        return len(errors) == 0, parsed, errors


class RegexConstraint:
    """Ensure output matches a regex pattern."""

    def __init__(self, pattern: str, extract_group: int = 0):
        self.pattern = re.compile(pattern, re.DOTALL)
        self.extract_group = extract_group

    def validate(self, text: str) -> Tuple[bool, str, List[str]]:
        m = self.pattern.search(text)
        if m:
            return True, m.group(self.extract_group) or text, []
        return False, text, [f"Output doesn't match pattern: {self.pattern.pattern[:60]}"]


class TypeConstraint:
    """Ensure output can be cast to a specific Python type."""

    TYPE_PARSERS = {
        "int": lambda x: int(x.strip()),
        "float": lambda x: float(x.strip()),
        "bool": lambda x: x.strip().lower() in ("true", "yes", "1"),
        "list": lambda x: [i.strip() for i in x.split(",") if i.strip()],
    }

    def __init__(self, type_name: str, min_val=None, max_val=None):
        self.type_name = type_name
        self.min_val = min_val
        self.max_val = max_val

    def validate(self, text: str) -> Tuple[bool, Any, List[str]]:
        parser = self.TYPE_PARSERS.get(self.type_name)
        if not parser:
            return False, text, [f"Unknown type: {self.type_name}"]
        try:
            # Extract first number/word
            cleaned = text.strip().split('\n')[0]
            value = parser(cleaned)
            if self.min_val is not None and value < self.min_val:
                return False, value, [f"Value {value} < min {self.min_val}"]
            if self.max_val is not None and value > self.max_val:
                return False, value, [f"Value {value} > max {self.max_val}"]
            return True, value, []
        except Exception as e:
            return False, text, [str(e)]


class ConstrainedGenerator:
    """Generate constrained output with automatic retry."""

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self._stats = {"generated": 0, "valid_first": 0, "retried": 0, "failed": 0}

    def generate(self, prompt: str, constraint,
                 llm_call: Callable[[str], str],
                 retry_hint: str = "") -> ConstraintResult:
        """Generate output that satisfies constraint, retrying if needed."""
        self._stats["generated"] += 1
        full_prompt = prompt
        
        # Add constraint instructions
        if isinstance(constraint, JSONConstraint):
            hint = "\nRespond with valid JSON only."
            if constraint.required_fields:
                hint += f"\nRequired fields: {', '.join(constraint.required_fields)}"
            full_prompt += hint
        elif isinstance(constraint, RegexConstraint):
            full_prompt += f"\nMatch pattern: {constraint.pattern.pattern[:80]}"
        elif isinstance(constraint, TypeConstraint):
            full_prompt += f"\nRespond with a single {constraint.type_name} value only."

        for attempt in range(1 + self.max_retries):
            try:
                output = llm_call(full_prompt)
            except Exception as e:
                return ConstraintResult(
                    output="", valid=False, errors=[str(e)], attempts=attempt
                )

            valid, parsed, errors = constraint.validate(output)
            if valid:
                if attempt == 0:
                    self._stats["valid_first"] += 1
                else:
                    self._stats["retried"] += 1
                return ConstraintResult(
                    output=output, valid=True, parsed=parsed,
                    errors=[], attempts=attempt + 1, retries=attempt,
                )

            # Retry with error hint
            if attempt < self.max_retries:
                full_prompt = (
                    f"{prompt}\n\n"
                    f"Previous response was invalid: {'; '.join(errors)}\n"
                    f"Please fix and try again. {retry_hint}"
                )

        self._stats["failed"] += 1
        return ConstraintResult(
            output=output, valid=False, parsed=parsed,
            errors=errors, attempts=1 + self.max_retries, retries=self.max_retries,
        )

    def json(self, prompt: str, llm: Callable, schema: Dict = None,
             required: List[str] = None) -> ConstraintResult:
        """Generate valid JSON."""
        return self.generate(prompt, JSONConstraint(schema, required), llm)

    def regex(self, prompt: str, llm: Callable, pattern: str) -> ConstraintResult:
        """Generate output matching regex."""
        return self.generate(prompt, RegexConstraint(pattern), llm)

    def typed(self, prompt: str, llm: Callable, type_name: str) -> ConstraintResult:
        """Generate typed output."""
        return self.generate(prompt, TypeConstraint(type_name), llm)

    def stats(self) -> Dict:
        return dict(self._stats)


# Singleton
_constrained: Optional[ConstrainedGenerator] = None


def get_constrained_generator() -> ConstrainedGenerator:
    global _constrained
    if _constrained is None:
        _constrained = ConstrainedGenerator()
    return _constrained
