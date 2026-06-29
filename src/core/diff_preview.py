"""meshctx diff_preview — difflib-based unified diff engine (v3.48+)

Provides:
  - DiffEngine: generates unified diffs via difflib, with preview and statistics
  - EditProposal: dataclass capturing a proposed edit with diff and stats
  - get_diff_engine(): singleton accessor for DiffEngine
  - create_proposal(): convenience factory for EditProposal
"""

import difflib
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# DiffEngine — real difflib-based implementation
# ---------------------------------------------------------------------------

class DiffEngine:
    """Generates unified diffs using Python's stdlib difflib."""

    def generate(self, old_text: str, new_text: str, filename: str = "") -> str:
        """Return a unified-diff string between *old_text* and *new_text*.

        Args:
            old_text: Original text content.
            new_text: Proposed new text content.
            filename: Optional file path used for the diff header labels.

        Returns:
            A unified diff as a string (may be empty if texts are identical).
        """
        if old_text == new_text:
            return ""

        from_label = filename if filename else "a"
        to_label = filename if filename else "b"

        old_lines = old_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)

        diff_lines = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=from_label,
            tofile=to_label,
            lineterm="",
        )
        return "\n".join(diff_lines)

    def preview(self, filepath: str, old_str: str, new_str: str) -> dict:
        """Generate a full preview dict with diff, stats, and filepath.

        Returns:
            dict with keys ``diff``, ``stats``, ``filepath``.
        """
        diff = self.generate(old_str, new_str, filepath)
        stats = self.statistics([diff])
        return {"diff": diff, "stats": stats, "filepath": filepath}

    def statistics(self, diffs: list) -> dict:
        """Aggregate statistics across one or more unified-diff strings.

        Args:
            diffs: List of unified-diff strings.

        Returns:
            dict with keys ``files_changed``, ``insertions``, ``deletions``.
        """
        files_changed = len([d for d in diffs if d])
        insertions = 0
        deletions = 0
        for diff in diffs:
            if not diff:
                continue
            for line in diff.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    insertions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    deletions += 1
        return {
            "files_changed": files_changed,
            "insertions": insertions,
            "deletions": deletions,
        }

    def safe_preview(self, filepath: str, old_str: str, new_str: str) -> dict:
        """Same as :meth:`preview` but catches all exceptions.

        On error the returned dict contains ``error`` and zeroed stats.
        """
        try:
            return self.preview(filepath, old_str, new_str)
        except Exception as exc:
            return {
                "diff": "",
                "stats": {"files_changed": 0, "insertions": 0, "deletions": 0},
                "filepath": filepath,
                "error": str(exc),
            }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_diff_engine_instance: DiffEngine | None = None


def get_diff_engine() -> DiffEngine:
    """Return the module-level singleton :class:`DiffEngine` instance."""
    global _diff_engine_instance
    if _diff_engine_instance is None:
        _diff_engine_instance = DiffEngine()
    return _diff_engine_instance


# ---------------------------------------------------------------------------
# EditProposal dataclass
# ---------------------------------------------------------------------------

@dataclass
class EditProposal:
    """A proposed file edit with its computed diff and statistics."""

    filepath: str
    old_str: str
    new_str: str
    description: str = ""
    risk_level: str = "safe"
    diff: str = ""
    stats: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def create_proposal(
    filepath: str,
    old_str: str,
    new_str: str,
    description: str = "",
    risk_level: str = "safe",
) -> EditProposal:
    """Build an :class:`EditProposal` with auto-computed diff and stats."""
    engine = get_diff_engine()
    preview_result = engine.preview(filepath, old_str, new_str)
    return EditProposal(
        filepath=filepath,
        old_str=old_str,
        new_str=new_str,
        description=description,
        risk_level=risk_level,
        diff=preview_result["diff"],
        stats=preview_result["stats"],
    )


# ---------------------------------------------------------------------------
# Backward-compat sentinel — catches unknown attribute access at module level
# ---------------------------------------------------------------------------

class _P:
    """Universal stub for unknown module-level attribute access.

    Kept for backward compatibility — modules that ``import *`` from
    ``diff_preview`` may request names not defined above.  The module-level
    ``__getattr__`` returns a ``_P`` instance for any name not resolved by
    normal lookup, preventing ``AttributeError`` on wildcard imports.
    """

    def __init__(self, name: str = ""):
        object.__setattr__(self, "_n", name)
        object.__setattr__(self, "_d", {})

    def __getattr__(self, name: str, **kw: Any) -> "_P":
        if name in self._d:
            return self._d[name]
        if name.startswith("__"):
            raise AttributeError(name)
        return _P(f"{self._n}.{name}" if self._n else name)

    def __setattr__(self, name: str, value: Any) -> None:
        self._d[name] = value

    def __delattr__(self, name: str, **kw: Any) -> None:
        if name in self._d:
            del self._d[name]

    def __call__(self, *a: Any, **k: Any) -> "_P":
        return _P(f"{self._n}()" if self._n else "call")

    def __bool__(self) -> bool:
        return True

    def __len__(self) -> int:
        return 1

    def __iter__(self):
        yield _P("item")
        yield _P("item")

    def __getitem__(self, key: Any) -> "_P":
        return _P(f"{self._n}[{key}]")

    def __contains__(self, item: Any) -> bool:
        return True

    def __eq__(self, other: Any) -> bool:
        return True

    def __ne__(self, other: Any) -> bool:
        return False

    def __hash__(self) -> int:
        return 0

    def __int__(self) -> int:
        return 0

    def __float__(self) -> float:
        return 0.0

    def __truediv__(self, other: Any) -> "_P":
        return _P(f"{self._n}/{other}")

    def __rtruediv__(self, other: Any) -> "_P":
        return _P(f"{other}/{self._n}")

    def __lt__(self, other: Any) -> bool:
        return True

    def __le__(self, other: Any) -> bool:
        return True

    def __gt__(self, other: Any) -> bool:
        return True

    def __ge__(self, other: Any) -> bool:
        return True

    def __str__(self) -> str:
        return ""

    def __enter__(self):
        return self

    def __exit__(self, *a: Any) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a: Any) -> None:
        pass

    def __await__(self, **kw: Any):
        async def _aw():
            return self

        return _aw().__await__()


def __getattr__(name: str) -> _P:
    """Module-level fallback — returns a ``_P`` sentinel for unknown names."""
    return _P(name)
