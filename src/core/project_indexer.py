"""Project Indexer — Real code indexer with scan/search/stats (v3.115+)

Scans directory trees, classifies files by language, builds searchable index.
Bridges to semantic_index.py for vector search when numpy is available.

Zero pip dependencies — Python stdlib only.
"""
__all__ = ['logger', 'FileEntry', 'ScanResult', 'SearchResult', 'get_indexer', 'get_index']


import fnmatch
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Language classifier ──────────────────────────────────────────────

_LANG_MAP: Dict[str, str] = {
    ".py": "Python", ".pyx": "Cython", ".pyi": "Python Stub",
    ".js": "JavaScript", ".mjs": "JavaScript Module", ".cjs": "CommonJS",
    ".ts": "TypeScript", ".tsx": "TypeScript React",
    ".jsx": "JavaScript React", ".vue": "Vue",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".java": "Java", ".kt": "Kotlin", ".scala": "Scala",
    ".c": "C", ".h": "C Header", ".cpp": "C++", ".cc": "C++",
    ".cxx": "C++", ".hpp": "C++ Header", ".hxx": "C++ Header",
    ".cs": "C#", ".swift": "Swift", ".m": "Objective-C", ".mm": "Objective-C++",
    ".r": "R", ".jl": "Julia", ".lua": "Lua",
    ".sh": "Shell", ".bash": "Bash", ".zsh": "Zsh", ".fish": "Fish",
    ".ps1": "PowerShell", ".bat": "Batch", ".cmd": "Batch",
    ".sql": "SQL", ".ddl": "DDL", ".dml": "DML",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".less": "Less", ".sass": "Sass",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML",
    ".toml": "TOML", ".ini": "INI", ".cfg": "Config",
    ".xml": "XML", ".svg": "SVG",
    ".md": "Markdown", ".mdx": "MDX", ".rst": "reStructuredText",
    ".tex": "LaTeX", ".bib": "BibTeX",
    ".dockerfile": "Dockerfile", ".dockerignore": "Docker Ignore",
    ".txt": "Text", ".log": "Log",
    ".proto": "Protobuf", ".graphql": "GraphQL", ".gql": "GraphQL",
    ".tf": "Terraform", ".hcl": "HCL",
    ".env": "Env", ".gitignore": "Git Ignore",
    ".lock": "Lockfile", ".toml": "TOML",
}

_SPECIAL_FILES: Dict[str, str] = {
    "Makefile": "Makefile", "CMakeLists.txt": "CMake",
    "Dockerfile": "Dockerfile", "Vagrantfile": "Vagrantfile",
    "Gemfile": "Ruby", "Rakefile": "Ruby", "Procfile": "Procfile",
    "Jenkinsfile": "Jenkinsfile", "Cargo.toml": "Rust Config",
}

_DEFAULT_IGNORE = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".next", ".nuxt", "dist", "build", ".cache",
    ".idea", ".vscode", ".DS_Store", "egg-info",
    ".eggs", ".hypothesis", "htmlcov", "coverage",
}


def _classify_language(filepath: str) -> str:
    """Classify a file by its extension or special name."""
    basename = os.path.basename(filepath)
    if basename in _SPECIAL_FILES:
        return _SPECIAL_FILES[basename]
    ext = os.path.splitext(basename)[1].lower()
    # Handle compound extensions
    if basename.lower().endswith(".d.ts"):
        return "TypeScript Declaration"
    return _LANG_MAP.get(ext, "Other")


def _count_lines(filepath: str) -> int:
    """Count lines in a text file."""
    try:
        with open(filepath, "rb") as f:
            # Fast line count via buffered read
            count = 0
            buf_size = 1024 * 1024  # 1 MB
            while True:
                chunk = f.read(buf_size)
                if not chunk:
                    break
                count += chunk.count(b"\n")
            return count
    except (OSError, PermissionError, UnicodeDecodeError):
        return 0


def _file_size(filepath: str) -> int:
    """Safe file size."""
    try:
        return os.path.getsize(filepath)
    except OSError:
        return 0


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class FileEntry:
    """Metadata for one indexed file."""
    relpath: str
    abspath: str
    language: str
    size_bytes: int
    lines: int
    extension: str = ""

    def to_dict(self) -> dict:
        return {
            "relpath": self.relpath,
            "abspath": self.abspath,
            "language": self.language,
            "size_bytes": self.size_bytes,
            "lines": self.lines,
            "extension": self.extension,
        }


class ScanResult:
    """Result of a directory scan."""
    total_files: int = 0
    total_size: int = 0
    total_lines: int = 0
    languages: Dict[str, int] = {}
    scan_duration_ms: float = 0
    last_scan: str = ""

    def to_dict(self) -> dict:
        return {
            "total_files": self.total_files,
            "total_size_bytes": self.total_size,
            "total_lines": self.total_lines,
            "languages": dict(sorted(self.languages.items(), key=lambda x: -x[1])),
            "scan_duration_ms": round(self.scan_duration_ms, 1),
            "last_scan": self.last_scan,
        }

    def __repr__(self) -> str:
        return f"ScanResult(files={self.total_files}, lines={self.total_lines}, langs={len(self.languages)})"


@dataclass
class SearchResult:
    """One search hit."""
    entry: FileEntry
    match_line: int = 0
    match_content: str = ""
    score: float = 1.0

    def to_dict(self) -> dict:
        d = self.entry.to_dict()
        d["match_line"] = self.match_line
        d["match_content"] = self.match_content
        d["score"] = self.score
        return d


# ── Indexer ───────────────────────────────────────────────────────────

class _Indexer:
    """Project code indexer with scan, index, search, stats."""

    def __init__(self, root: str = "."):
        self.project_root = os.path.abspath(root)
        self._lock = threading.RLock()
        self._entries: Dict[str, FileEntry] = {}  # relpath -> FileEntry
        self._by_lang: Dict[str, List[str]] = {}  # lang -> [relpath, ...]
        self._last_stats: Optional[ScanResult] = None
        self._semantic_index = None

    # -- public API (matches stub signature) --

    def scan(self, **kw) -> ScanResult:
        """Scan directory tree and return ScanResult.

        Options:
          ignore_dirs: set of dir names to skip
          patterns: list of glob patterns to filter (e.g. ['*.py', '*.md'])
          max_depth: max directory depth
        """
        ignore_dirs = set(kw.get("ignore_dirs", _DEFAULT_IGNORE))
        patterns = kw.get("patterns")
        max_depth = kw.get("max_depth")

        t0 = time.monotonic()
        result = ScanResult()
        result.last_scan = time.strftime("%Y-%m-%dT%H:%M:%S")

        for dirpath, dirnames, filenames in os.walk(self.project_root):
            # Filter dirs
            dirnames[:] = [
                d for d in dirnames
                if d not in ignore_dirs and not d.startswith(".")
            ]
            # Depth limit
            if max_depth is not None:
                depth = dirpath[len(self.project_root):].count(os.sep)
                if depth >= max_depth:
                    dirnames[:] = []

            for fname in sorted(filenames):
                abspath = os.path.join(dirpath, fname)
                relpath = os.path.relpath(abspath, self.project_root)

                # Pattern filter
                if patterns and not any(
                    fnmatch.fnmatch(relpath, p) or fnmatch.fnmatch(fname, p)
                    for p in patterns
                ):
                    continue

                lang = _classify_language(relpath)
                size = _file_size(abspath)
                lines = _count_lines(abspath)
                ext = os.path.splitext(fname)[1].lower()

                result.total_files += 1
                result.total_size += size
                result.total_lines += lines
                result.languages[lang] = result.languages.get(lang, 0) + 1

                entry = FileEntry(
                    relpath=relpath, abspath=abspath,
                    language=lang, size_bytes=size,
                    lines=lines, extension=ext,
                )
                with self._lock:
                    self._entries[relpath] = entry

        result.scan_duration_ms = (time.monotonic() - t0) * 1000
        with self._lock:
            self._last_stats = result
        return result

    def index(self, *a, **kw):
        """Index the project (alias for scan + build semantic index).

        The stub took *a, **kw and passed. We do real work.
        """
        result = self.scan(**kw)

        # Build language index
        with self._lock:
            self._by_lang.clear()
            for relpath, entry in self._entries.items():
                self._by_lang.setdefault(entry.language, []).append(relpath)

            for v in self._by_lang.values():
                v.sort()

        # Try semantic index
        try:
            from src.core.semantic_index import get_semantic_index
            si = get_semantic_index()
            if si is not None:
                self._semantic_index = si
                # Index file paths as semantic entries (metadata-only for now)
                for relpath, entry in self._entries.items():
                    try:
                        si.add(
                            relpath,
                            [float(hash(relpath) % 1000) / 1000.0] * 128,  # placeholder vec
                            metadata={"language": entry.language, "path": relpath},
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        return result

    def search(self, *a, **kw) -> list:
        """Search indexed files.

        Options:
          query: str — substring match on filename or content
          language: str — filter by language
          file_pattern: str — fnmatch glob
          regex: str — regex to search in file contents
          max_results: int (default 50)
        """
        query = kw.get("query", a[0] if a else "")
        language = kw.get("language")
        file_pattern = kw.get("file_pattern")
        regex_str = kw.get("regex")
        max_results = kw.get("max_results", 50)

        regex = None
        if regex_str:
            try:
                regex = re.compile(regex_str, re.IGNORECASE)
            except re.error:
                pass

        results: List[dict] = []
        with self._lock:
            candidates = list(self._entries.values())

        for entry in candidates:
            if language and entry.language.lower() != language.lower():
                continue
            if file_pattern and not fnmatch.fnmatch(entry.relpath, file_pattern):
                continue

            # Filename match
            if query:
                if query.lower() not in os.path.basename(entry.relpath).lower():
                    # Try content search
                    if regex or query:
                        try:
                            with open(entry.abspath, "r", errors="ignore") as f:
                                content = ""
                                for i, line in enumerate(f, 1):
                                    if regex and regex.search(line):
                                        content = line.rstrip()
                                        sr = SearchResult(entry=entry, match_line=i, match_content=content).to_dict()
                                        results.append(sr)
                                        break
                                    elif query and query.lower() in line.lower():
                                        content = line.rstrip()
                                        sr = SearchResult(entry=entry, match_line=i, match_content=content).to_dict()
                                        results.append(sr)
                                        break
                            continue
                        except Exception:
                            pass
                    continue

            results.append(SearchResult(entry=entry).to_dict())
            if len(results) >= max_results:
                break

        return results[:max_results]

    def stats(self) -> dict:
        """Return index statistics."""
        with self._lock:
            if self._last_stats:
                return self._last_stats.to_dict()
            return {
                "total_files": len(self._entries),
                "total_size_bytes": sum(e.size_bytes for e in self._entries.values()),
                "total_lines": sum(e.lines for e in self._entries.values()),
                "languages": {},
                "scan_duration_ms": 0,
                "last_scan": "",
                "project_root": self.project_root,
                "semantic_index": self._semantic_index is not None,
            }


_indexer = _Indexer()


def get_indexer(root: str = ".") -> _Indexer:
    """Factory: get or create an indexer for a project root."""
    if root == "." or os.path.abspath(root) == _indexer.project_root:
        return _indexer
    return _Indexer(root)


get_index = _Indexer.search  # backward compat alias


# ── _P universal proxy (backward compat) ──────────────────────────────

