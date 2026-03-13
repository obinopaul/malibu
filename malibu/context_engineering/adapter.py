"""Production-safe runtime context assembly for Malibu.

This adapter integrates local/project context files with deterministic limits,
providing robust prompt context without exceeding reasonable token budgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from malibu.telemetry.logging import get_logger

_log = get_logger(__name__)

# Ordered by priority. Earlier entries get more consistent inclusion.
_CONTEXT_FILE_CANDIDATES = [
    ".malibu/context.md",
    ".malibu/instructions.md",
    "MALIBU.md",
    "AGENTS.md",
    "README.md",
]

_MAX_FILE_CHARS = 24_000
_MAX_TOTAL_CHARS = 72_000
_MAX_PARENT_DEPTH = 4


@dataclass(frozen=True)
class ContextDocument:
    """Resolved context document metadata."""

    path: Path
    source_label: str


def _iter_search_roots(cwd: Path) -> list[Path]:
    """Yield cwd and selected parents, stopping at git root when found."""
    roots: list[Path] = []
    current = cwd.resolve()
    for _ in range(_MAX_PARENT_DEPTH + 1):
        roots.append(current)
        if (current / ".git").exists():
            break
        if current.parent == current:
            break
        current = current.parent
    return roots


def _find_context_docs(cwd: Path) -> list[ContextDocument]:
    seen: set[Path] = set()
    docs: list[ContextDocument] = []

    for root in _iter_search_roots(cwd):
        rel_root = "." if root == cwd else str(root)
        for rel_name in _CONTEXT_FILE_CANDIDATES:
            candidate = (root / rel_name).resolve()
            if candidate in seen or not candidate.is_file():
                continue
            seen.add(candidate)
            docs.append(ContextDocument(path=candidate, source_label=f"{rel_name} ({rel_root})"))

    return docs


def _read_limited(path: Path) -> str | None:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if len(data) > _MAX_FILE_CHARS:
        return data[:_MAX_FILE_CHARS] + "\n\n[...truncated for context budget...]"
    return data


def build_runtime_context(cwd: str) -> str | None:
    """Build runtime context block for the Malibu system prompt.

    Reads context documents from cwd and a bounded set of parent directories,
    then concatenates them with explicit provenance headers.

    Returns:
        Combined markdown context block or None if no context docs found.
    """
    root = Path(cwd)
    if not root.exists():
        return None

    docs = _find_context_docs(root)
    if not docs:
        return None

    sections: list[str] = []
    total = 0

    for doc in docs:
        content = _read_limited(doc.path)
        if not content:
            continue

        section = f"### Context Source: {doc.source_label}\n\n{content}".strip()
        projected = total + len(section)
        if projected > _MAX_TOTAL_CHARS:
            _log.info(
                "context_budget_reached",
                max_chars=_MAX_TOTAL_CHARS,
                included=len(sections),
            )
            break

        sections.append(section)
        total = projected

    return "\n\n".join(sections) if sections else None
