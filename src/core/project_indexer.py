"""
MeshCtx Project Indexer — Code-Aware Context Engine
=====================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

Indexes project files for intelligent context retrieval.
Watches file changes and maintains a lightweight search index
for /context commands — inspired by Cursor/Windsurf's codebase awareness.

License: AGPLv3 for non-commercial use only.
         Commercial use REQUIRES a separate license.
         Contact: license@meshctx.com
"""
import os
import re
import time
import json
import hashlib
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
import logging
import threading

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB max per file
MAX_INDEX_FILES = 5000
INDEX_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".sh", ".bash", ".zsh", ".rs", ".go", ".java", ".c", ".cpp", ".h",
    ".rb", ".php", ".swift", ".kt", ".sql", ".r", ".m", ".jl",
    ".dockerfile", ".env", ".gitignore", ".Makefile",
}
IGNORE_PATTERNS = [
    "node_modules", "__pycache__", ".git", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    "*.pyc", "*.pyo", "*.so", "*.dll", "*.exe", "*.bin",
    "*.zip", "*.tar", "*.gz", "*.7z", "*.rar",
    "package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock",
]


@dataclass
class FileSummary:
    """Lightweight summary of an indexed file."""
    path: str          # Relative path from project root
    size: int          # File size in bytes
    mtime: float       # Last modification time
    hash: str          # MD5 hash of content
    language: str      # Detected language
    symbols: List[str] # Top-level symbols (functions/classes/imports)
    summary: str       # First 200 chars as summary
    line_count: int    # Number of lines


@dataclass
class IndexStats:
    """Statistics for the project index."""
    total_files: int = 0
    total_size: int = 0
    total_lines: int = 0
    languages: Dict[str, int] = field(default_factory=dict)
    last_scan: float = 0
    scan_duration_ms: float = 0


class ProjectIndexer:
    """Indexes project files for intelligent context retrieval."""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.index: Dict[str, FileSummary] = {}  # relpath → summary
        self.stats = IndexStats()
        self._lock = threading.Lock()
        self._watcher: Optional[threading.Thread] = None
        self._running = False

    def scan(self, force: bool = False) -> IndexStats:
        """
        Scan project directory and build/update index.

        Args:
            force: If True, re-scan all files even if unchanged.

        Returns:
            Updated IndexStats
        """
        t_start = time.time()
        new_index: Dict[str, FileSummary] = {}
        total_size = 0
        total_lines = 0
        total_files = 0
        languages: Dict[str, int] = {}

        for root, dirs, files in os.walk(self.project_root):
            # Filter directories
            dirs[:] = [d for d in dirs if not self._is_ignored(d)]

            for filename in files:
                if total_files >= MAX_INDEX_FILES:
                    break

                if self._is_ignored(filename):
                    continue

                filepath = os.path.join(root, filename)
                relpath = os.path.relpath(filepath, self.project_root)

                # Check extension
                ext = os.path.splitext(filename)[1].lower()
                if filename == "Dockerfile":
                    ext = ".dockerfile"
                elif filename == "Makefile":
                    ext = ".Makefile"

                if ext not in INDEX_EXTENSIONS and filename not in (".env", ".gitignore", "Dockerfile", "Makefile"):
                    continue

                try:
                    stat = os.stat(filepath)
                    if stat.st_size > MAX_FILE_SIZE:
                        continue

                    # Skip if unchanged and not forcing
                    if not force and relpath in self.index:
                        old = self.index[relpath]
                        if old.mtime == stat.st_mtime and old.size == stat.st_size:
                            new_index[relpath] = old
                            total_size += old.size
                            total_lines += old.line_count
                            total_files += 1
                            languages[old.language] = languages.get(old.language, 0) + 1
                            continue

                    # Read and index
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()

                    content_hash = hashlib.md5(content.encode()).hexdigest()
                    lines = content.split("\n")
                    line_count = len(lines)
                    symbols = self._extract_symbols(content, ext)
                    language = self._detect_language(ext, filename)
                    summary = content[:200].replace("\n", " ").strip()

                    entry = FileSummary(
                        path=relpath,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                        hash=content_hash,
                        language=language,
                        symbols=symbols,
                        summary=summary,
                        line_count=line_count,
                    )

                    new_index[relpath] = entry
                    total_size += stat.st_size
                    total_lines += line_count
                    total_files += 1
                    languages[language] = languages.get(language, 0) + 1

                except (IOError, UnicodeDecodeError, PermissionError) as e:
                    logger.debug(f"Skipping {relpath}: {e}")
                    continue

        with self._lock:
            self.index = new_index
            self.stats = IndexStats(
                total_files=total_files,
                total_size=total_size,
                total_lines=total_lines,
                languages=languages,
                last_scan=time.time(),
                scan_duration_ms=(time.time() - t_start) * 1000,
            )

        logger.info(f"Indexed {total_files} files ({total_lines} lines) in {self.stats.scan_duration_ms:.0f}ms")
        return self.stats

    def search(self, query: str, top_k: int = 10) -> List[FileSummary]:
        """
        Search indexed files for query.

        Args:
            query: Search terms (space-separated, AND logic)
            top_k: Max results

        Returns:
            List of matching FileSummary objects
        """
        terms = [t.lower() for t in query.split() if t]
        if not terms:
            return []

        results: List[Tuple[FileSummary, int]] = []

        with self._lock:
            for entry in self.index.values():
                score = 0
                text = (entry.path + " " + entry.summary + " " + " ".join(entry.symbols)).lower()

                for term in terms:
                    if term in text:
                        score += 1
                    # Bonus for symbol match
                    for sym in entry.symbols:
                        if term in sym.lower():
                            score += 2

                if score > 0:
                    results.append((entry, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in results[:top_k]]

    def get_context(self, query: str, max_chars: int = 8000) -> str:
        """
        Build context string from indexed files matching query.

        Args:
            query: What to look for (e.g., "auth login handler")
            max_chars: Maximum characters to return

        Returns:
            Context block with file contents
        """
        matches = self.search(query, top_k=5)
        if not matches:
            return f"[No files matching '{query}' found in project index]"

        context_parts = [f"[Project Context: {len(matches)} files matched '{query}']"]

        total_chars = 0
        for m in matches:
            try:
                filepath = self.project_root / m.path
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                header = f"\n--- {m.path} ({m.line_count} lines, {m.language}) ---\n"
                if total_chars + len(header) > max_chars:
                    break

                remaining = max_chars - total_chars - len(header)
                if len(content) > remaining:
                    content = content[:remaining] + "\n... [truncated]"

                context_parts.append(header + content)
                total_chars += len(header) + len(content)

            except (IOError, PermissionError):
                context_parts.append(f"\n--- {m.path} [unable to read] ---")
                continue

        return "\n".join(context_parts)

    def start_watching(self, interval: float = 5.0):
        """Start background file watcher (re-scans periodically)."""
        if self._running:
            return

        self._running = True

        def _watch_loop():
            while self._running:
                time.sleep(interval)
                try:
                    self.scan(force=False)
                except Exception as e:
                    logger.error(f"Watcher scan error: {e}")

        self._watcher = threading.Thread(target=_watch_loop, daemon=True)
        self._watcher.start()
        logger.info(f"File watcher started (interval={interval}s)")

    def stop_watching(self):
        """Stop background file watcher."""
        self._running = False

    # ─── Helpers ──────────────────────────────────────

    def _is_ignored(self, name: str) -> bool:
        for pattern in IGNORE_PATTERNS:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False

    def _detect_language(self, ext: str, filename: str) -> str:
        lang_map = {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".jsx": "JSX", ".tsx": "TSX", ".html": "HTML", ".css": "CSS",
            ".scss": "SCSS", ".md": "Markdown", ".json": "JSON",
            ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
            ".sh": "Shell", ".bash": "Shell", ".rs": "Rust",
            ".go": "Go", ".java": "Java", ".c": "C", ".cpp": "C++",
            ".h": "C/C++ Header", ".rb": "Ruby", ".php": "PHP",
            ".swift": "Swift", ".kt": "Kotlin", ".sql": "SQL",
            ".r": "R", ".m": "MATLAB", ".jl": "Julia",
            ".dockerfile": "Dockerfile", ".Makefile": "Makefile",
        }
        return lang_map.get(ext, filename.split(".")[-1] if "." in filename else "unknown")

    def _extract_symbols(self, content: str, ext: str) -> List[str]:
        """Extract function/class/import names from source code."""
        symbols = []

        try:
            if ext == ".py":
                # Python: def, class, import
                for line in content.split("\n"):
                    line = line.strip()
                    m = re.match(r'^(?:async\s+)?def\s+(\w+)', line)
                    if m:
                        symbols.append(f"def:{m.group(1)}")
                        continue
                    m = re.match(r'^class\s+(\w+)', line)
                    if m:
                        symbols.append(f"class:{m.group(1)}")
                        continue
                    m = re.match(r'^(?:from\s+\S+\s+)?import\s+(\S+)', line)
                    if m:
                        for imp in m.group(1).split(","):
                            imp = imp.strip()
                            if imp:
                                symbols.append(f"import:{imp}")

            elif ext in (".js", ".ts", ".jsx", ".tsx"):
                for line in content.split("\n"):
                    line = line.strip()
                    m = re.match(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', line)
                    if m:
                        symbols.append(f"function:{m.group(1)}")
                        continue
                    m = re.match(r'(?:export\s+)?class\s+(\w+)', line)
                    if m:
                        symbols.append(f"class:{m.group(1)}")
                        continue
                    m = re.match(r'(?:const|let|var)\s+(\w+)\s*=', line)
                    if m:
                        symbols.append(f"var:{m.group(1)}")

            elif ext in (".go", ".rs"):
                for line in content.split("\n"):
                    line = line.strip()
                    m = re.match(r'^fn\s+(\w+)', line)
                    if m:
                        symbols.append(f"fn:{m.group(1)}")
                    m = re.match(r'^func\s+(\w+)', line)
                    if m:
                        symbols.append(f"func:{m.group(1)}")
                    m = re.match(r'^(?:pub\s+)?(?:type\s+)?struct\s+(\w+)', line)
                    if m:
                        symbols.append(f"struct:{m.group(1)}")

        except Exception:
            pass

        return symbols[:50]  # Cap at 50 symbols per file


# ─── Module-level helpers ────────────────────────────────
_indexers: Dict[str, ProjectIndexer] = {}


def get_indexer(project_root: str = ".") -> ProjectIndexer:
    """Get or create a ProjectIndexer for the given project root."""
    key = str(Path(project_root).resolve())
    if key not in _indexers:
        idx = ProjectIndexer(project_root)
        idx.scan()
        _indexers[key] = idx
    return _indexers[key]
