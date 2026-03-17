"""Wrapper adapting solidlsp to our SymbolRetriever API.

This module provides a thin adapter layer between solidlsp's SolidLanguageServer
and our existing symbol tools API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from threading import RLock
import time
from typing import Any

from vibe.core.workspace import canonical_workspace_root
from vibe.core.tools.lsp import ls_types
from vibe.core.tools.lsp.ls import SolidLanguageServer
from vibe.core.tools.lsp.ls_config import Language, LanguageServerConfig
from vibe.core.tools.lsp.ls_utils import PathUtils
from vibe.core.tools.lsp.lsp_protocol_handler.lsp_types import PositionEncodingKind
from vibe.core.tools.lsp.settings import SolidLSPSettings

from .symbol import Symbol, SymbolKind

logger = logging.getLogger(__name__)

_WORKSPACE_SCAN_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    ".vscode",
    ".idea",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "target",
    "out",
    "coverage",
    ".mypy_cache",
    ".pytest_cache",
}

# Mapping from file extensions to Language enum
_EXTENSION_TO_LANGUAGE: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".pyi": Language.PYTHON,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TYPESCRIPT,
    ".js": Language.TYPESCRIPT,  # TypeScript server handles JS too
    ".jsx": Language.TYPESCRIPT,
    ".mjs": Language.TYPESCRIPT,
    ".rs": Language.RUST,
    ".go": Language.GO,
    ".java": Language.JAVA,
    ".kt": Language.KOTLIN,
    ".kts": Language.KOTLIN,
    ".rb": Language.RUBY,
    ".dart": Language.DART,
    ".c": Language.CPP,
    ".cpp": Language.CPP,
    ".cc": Language.CPP,
    ".cxx": Language.CPP,
    ".h": Language.CPP,
    ".hpp": Language.CPP,
    ".php": Language.PHP,
    ".cs": Language.CSHARP,
    ".swift": Language.SWIFT,
    ".sh": Language.BASH,
    ".bash": Language.BASH,
    ".ex": Language.ELIXIR,
    ".exs": Language.ELIXIR,
    ".clj": Language.CLOJURE,
    ".cljc": Language.CLOJURE,
    ".cljs": Language.CLOJURE,
    ".elm": Language.ELM,
    ".tf": Language.TERRAFORM,
    ".lua": Language.LUA,
    ".zig": Language.ZIG,
    ".nix": Language.NIX,
    ".yaml": Language.YAML,
    ".yml": Language.YAML,
    ".md": Language.MARKDOWN,
    ".erl": Language.ERLANG,
    ".hrl": Language.ERLANG,
    ".r": Language.R,
    ".R": Language.R,
    ".scala": Language.SCALA,
    ".sc": Language.SCALA,
    ".jl": Language.JULIA,
    ".f90": Language.FORTRAN,
    ".f95": Language.FORTRAN,
    ".f03": Language.FORTRAN,
    ".hs": Language.HASKELL,
    ".lhs": Language.HASKELL,
}


def get_language_from_path(file_path: str | Path) -> Language | None:
    """Get Language enum from file path.

    Args:
        file_path: Path to the file

    Returns:
        Language enum or None if unsupported
    """
    ext = Path(file_path).suffix.lower()
    return _EXTENSION_TO_LANGUAGE.get(ext)


class LSPServerWrapper:
    """Wrapper adapting solidlsp to our symbol tools API.

    This class manages SolidLanguageServer instances and provides
    methods that match our existing SymbolRetriever interface.
    """

    def __init__(
        self,
        workspace_root: str | Path | None = None,
        settings: SolidLSPSettings | None = None,
    ) -> None:
        """Initialize the wrapper.

        Args:
            workspace_root: Root directory of the workspace
            settings: Optional solidlsp settings
        """
        self._workspace_root = canonical_workspace_root(workspace_root)
        self._settings = settings or SolidLSPSettings()
        self._servers: dict[Language, SolidLanguageServer] = {}
        self._startup_errors: dict[Language, str] = {}

    @property
    def workspace_root(self) -> Path:
        """Get the workspace root directory."""
        return self._workspace_root

    @workspace_root.setter
    def workspace_root(self, value: Path | str) -> None:
        """Set the workspace root directory."""
        self._workspace_root = canonical_workspace_root(value)

    def get_server(self, language: Language) -> SolidLanguageServer | None:
        """Get or create a language server for the specified language.

        Args:
            language: Language enum

        Returns:
            SolidLanguageServer instance or None if creation fails
        """
        if language in self._servers:
            server = self._servers[language]
            if server.is_running():
                return server
            # Server died, remove it
            del self._servers[language]

        try:
            server = SolidLanguageServer.create(
                config=LanguageServerConfig(code_language=language),
                repository_root_path=str(self._workspace_root),
                solidlsp_settings=self._settings,
            )
            server.start()
            self._servers[language] = server
            self._startup_errors.pop(language, None)
            return server
        except Exception as e:
            self._startup_errors[language] = str(e)
            logger.warning(f"Failed to create {language.name} server: {e}")
            return None

    def get_server_for_file(self, file_path: str | Path) -> SolidLanguageServer | None:
        """Get a language server for the specified file.

        Args:
            file_path: Path to the file

        Returns:
            SolidLanguageServer instance or None
        """
        language = get_language_from_path(file_path)
        if language is None:
            logger.debug(f"No language server for {file_path}")
            return None
        return self.get_server(language)

    def get_position_encoding(self, file_path: str | Path) -> str:
        server = self.get_server_for_file(file_path)
        if server is None:
            return PositionEncodingKind.UTF16.value

        encoding = getattr(server, "position_encoding", PositionEncodingKind.UTF16)
        if isinstance(encoding, PositionEncodingKind):
            return encoding.value
        return str(encoding)

    def get_document_symbols(self, file_path: str | Path) -> list[Symbol]:
        """Get all symbols in a document.

        Args:
            file_path: Path to the file

        Returns:
            List of Symbol objects
        """
        path = Path(file_path).resolve()
        server = self.get_server_for_file(path)
        if server is None:
            return []

        # Get relative path from workspace root
        try:
            relative_path = path.relative_to(self._workspace_root)
        except ValueError:
            relative_path = path

        try:
            doc_symbols = server.request_document_symbols(str(relative_path))
            return self._convert_unified_symbols(doc_symbols.root_symbols, str(path))
        except Exception as e:
            logger.warning(f"Failed to get document symbols for {path}: {e}")
            return []

    def find_references(
        self,
        file_path: str | Path,
        line: int,
        character: int,
        include_declaration: bool = True,
    ) -> list[dict[str, Any]]:
        """Find all references to a symbol at position.

        Args:
            file_path: Path to the file
            line: 0-indexed line number
            character: 0-indexed character offset
            include_declaration: Whether to include the symbol declaration

        Returns:
            List of reference locations
        """
        path = Path(file_path).resolve()
        server = self.get_server_for_file(path)
        if server is None:
            return []

        try:
            relative_path = path.relative_to(self._workspace_root)
        except ValueError:
            relative_path = path

        try:
            locations = server.request_references(
                str(relative_path),
                line,
                character,
                include_declaration=include_declaration,
            )
            return [
                {
                    "file": self._normalize_location_path(loc),
                    "line": loc["range"]["start"]["line"] + 1,
                    "character": loc["range"]["start"]["character"],
                    "end_line": loc["range"]["end"]["line"] + 1,
                    "end_character": loc["range"]["end"]["character"],
                }
                for loc in locations
            ]
        except Exception as e:
            logger.warning(f"Failed to get references: {e}")
            return []

    def get_definition(
        self,
        file_path: str | Path,
        line: int,
        character: int,
    ) -> list[dict[str, Any]]:
        """Get definition location(s) for symbol at position.

        Args:
            file_path: Path to the file
            line: 0-indexed line number
            character: 0-indexed character offset

        Returns:
            List of definition locations
        """
        path = Path(file_path).resolve()
        server = self.get_server_for_file(path)
        if server is None:
            return []

        try:
            relative_path = path.relative_to(self._workspace_root)
        except ValueError:
            relative_path = path

        try:
            locations = server.request_definition(str(relative_path), line, character)
            return [
                {
                    "file": self._normalize_location_path(loc),
                    "line": loc["range"]["start"]["line"] + 1,
                    "character": loc["range"]["start"]["character"],
                }
                for loc in locations
            ]
        except Exception as e:
            logger.warning(f"Failed to get definition: {e}")
            return []

    def rename_symbol(
        self,
        file_path: str | Path,
        line: int,
        character: int,
        new_name: str,
    ) -> dict[str, list[dict[str, Any]]] | None:
        """Rename a symbol across the workspace.

        Args:
            file_path: Path to file containing the symbol
            line: 0-indexed line number
            character: 0-indexed character offset
            new_name: New name for the symbol

        Returns:
            Dict mapping file paths to text edits, or None if failed
        """
        path = Path(file_path).resolve()
        server = self.get_server_for_file(path)
        if server is None:
            return None

        try:
            relative_path = path.relative_to(self._workspace_root)
        except ValueError:
            relative_path = path

        try:
            workspace_edit = server.request_rename_symbol_edit(
                str(relative_path), line, character, new_name
            )
            if workspace_edit is None:
                return None

            return self._parse_workspace_edit(workspace_edit)
        except Exception as e:
            logger.warning(f"Failed to rename symbol: {e}")
            return None

    def get_workspace_symbols(self, query: str) -> list[Symbol]:
        """Search for symbols in the workspace.

        Args:
            query: Search query

        Returns:
            List of matching symbols
        """
        symbols_by_key: dict[tuple[str, str, int, int, int], Symbol] = {}
        for language in self._iter_workspace_search_languages():
            server = self.get_server(language)
            if server is None:
                continue

            try:
                if not (raw_symbols := server.request_workspace_symbol(query)):
                    continue

                for symbol in self._convert_unified_symbols(raw_symbols, ""):
                    key = (
                        symbol.file_path,
                        symbol.name_path,
                        symbol.start_line,
                        symbol.start_character,
                        int(symbol.kind),
                    )
                    symbols_by_key.setdefault(key, symbol)
            except Exception as e:
                logger.debug(f"Workspace symbol search failed for {language}: {e}")

        return list(symbols_by_key.values())

    def get_last_startup_error(self, language: Language) -> str | None:
        """Return the most recent startup error for a language server, if any."""
        return self._startup_errors.get(language)

    def get_diagnostics(
        self,
        file_path: str | Path,
        *,
        severity_filter: int = 1,
        max_diagnostics: int = 20,
        timeout: float = 3.0,
    ) -> list[dict[str, Any]]:
        """Get LSP diagnostics for a file after a change.

        Notifies the language server of file changes and retrieves diagnostics.

        Args:
            file_path: Path to the file to check.
            severity_filter: Maximum severity to include (1=Error, 2=Warning, etc.)
            max_diagnostics: Cap on number of diagnostics returned.
            timeout: Maximum seconds to wait for diagnostics.

        Returns:
            List of diagnostic dicts with keys: severity, message, line, character.
            Empty list if no LSP server is available or no diagnostics found.
        """
        server = self.get_server_for_file(file_path)
        if not server:
            return []

        try:
            abs_path = Path(file_path).resolve()
            rel_path = abs_path.relative_to(self._workspace_root)
        except (ValueError, OSError):
            return []

        try:
            diagnostics = server.request_text_document_diagnostics(str(rel_path))
        except Exception as e:
            logger.debug("LSP diagnostics request failed for %s: %s", file_path, e)
            return []

        results = []
        for diag in diagnostics:
            sev = diag.get("severity", 4)
            if sev > severity_filter:
                continue
            range_data = diag.get("range", {})
            start = range_data.get("start", {})
            results.append({
                "severity": "Error" if sev == 1 else "Warning" if sev == 2 else "Info",
                "message": diag.get("message", ""),
                "line": start.get("line", 0) + 1,  # 1-based for display
                "character": start.get("character", 0),
            })
            if len(results) >= max_diagnostics:
                break

        return results

    def shutdown(self) -> None:
        """Shutdown all running language servers."""
        for language, server in list(self._servers.items()):
            try:
                server.stop()
            except Exception as e:
                logger.warning(f"Failed to stop {language} server: {e}")
            del self._servers[language]

    def _convert_unified_symbols(
        self,
        unified_symbols: list[ls_types.UnifiedSymbolInformation],
        file_path: str,
        parent: Symbol | None = None,
    ) -> list[Symbol]:
        """Convert solidlsp UnifiedSymbolInformation to our Symbol class.

        Args:
            unified_symbols: List of UnifiedSymbolInformation from solidlsp
            file_path: Default file path for symbols without location
            parent: Parent symbol if nested

        Returns:
            List of Symbol objects
        """
        symbols = []

        for usym in unified_symbols:
            # Extract range info
            range_data = usym.get("range", {})
            start = range_data.get("start", {"line": 0, "character": 0})
            end = range_data.get("end", {"line": 0, "character": 0})

            # Get file path from location if available
            location = usym.get("location")
            sym_file = file_path
            if location:
                abs_path = location.get("absolutePath")
                if abs_path:
                    sym_file = abs_path
                elif location.get("uri", "").startswith("file://"):
                    sym_file = PathUtils.uri_to_path(location["uri"])

            symbol = Symbol(
                name=usym["name"],
                kind=SymbolKind.from_value(usym.get("kind", 13)),
                file_path=sym_file,
                start_line=start.get("line", 0),
                start_character=start.get("character", 0),
                end_line=end.get("line", 0),
                end_character=end.get("character", 0),
                container_name=usym.get("containerName"),
                parent=parent,
            )

            # Convert children recursively
            children_data = usym.get("children", [])
            if children_data:
                symbol.children = self._convert_unified_symbols(
                    children_data, sym_file, parent=symbol
                )

            symbols.append(symbol)

        return symbols

    @staticmethod
    def _normalize_location_path(location: Any) -> str:
        absolute_path = location.get("absolutePath")
        if isinstance(absolute_path, str) and absolute_path:
            return absolute_path

        uri = location.get("uri", "")
        if isinstance(uri, str) and uri.startswith("file://"):
            return PathUtils.uri_to_path(uri)
        return str(uri)

    def _iter_workspace_search_languages(self) -> list[Language]:
        preferred_languages = [
            language
            for language in self._discover_workspace_languages()
            if not language.is_experimental()
        ]
        if not preferred_languages:
            preferred_languages = [Language.PYTHON, Language.TYPESCRIPT]

        return list(dict.fromkeys([
            *self._servers.keys(),
            *preferred_languages,
        ]))

    def _discover_workspace_languages(self) -> list[Language]:
        discovered: set[Language] = set()
        pending_dirs = [self._workspace_root]

        while pending_dirs:
            current_dir = pending_dirs.pop()
            try:
                entries = list(current_dir.iterdir())
            except OSError:
                continue

            for entry in entries:
                if entry.is_dir():
                    if self._should_skip_workspace_dir(entry):
                        continue
                    pending_dirs.append(entry)
                    continue

                if (language := get_language_from_path(entry)) is not None:
                    discovered.add(language)

        ordered_languages = list(Language.iter_all(include_experimental=True))
        return [language for language in ordered_languages if language in discovered]

    @staticmethod
    def _should_skip_workspace_dir(path: Path) -> bool:
        name = path.name
        if name in _WORKSPACE_SCAN_IGNORE_DIRS:
            return True
        return name.startswith(".") and name not in {".github"}

    def _parse_workspace_edit(
        self,
        workspace_edit: ls_types.WorkspaceEdit,
    ) -> dict[str, list[dict[str, Any]]]:
        """Parse solidlsp WorkspaceEdit into simplified format.

        Returns:
            Dict mapping file paths to list of text edits
        """
        result: dict[str, list[dict[str, Any]]] = {}

        # Use the helper function from ls_types
        from vibe.core.tools.lsp.ls_types import extract_text_edits

        try:
            changes = extract_text_edits(workspace_edit)
            for uri, edits in changes.items():
                file_path = (
                    PathUtils.uri_to_path(uri) if uri.startswith("file://") else uri
                )

                parsed_edits = []
                for edit in edits:
                    range_data = edit.get("range", {})
                    parsed_edits.append({
                        "start_line": range_data.get("start", {}).get("line", 0),
                        "start_character": range_data.get("start", {}).get("character", 0),
                        "end_line": range_data.get("end", {}).get("line", 0),
                        "end_character": range_data.get("end", {}).get("character", 0),
                        "new_text": edit.get("newText", ""),
                    })

                result[file_path] = parsed_edits
        except Exception as e:
            logger.warning(f"Failed to parse workspace edit: {e}")

        return result


@dataclass(slots=True)
class _WrapperState:
    wrapper: LSPServerWrapper
    last_used_at: float = field(default_factory=time.monotonic)


class LSPWrapperRegistry:
    def __init__(self) -> None:
        self._wrappers: dict[Path, _WrapperState] = {}
        self._lock = RLock()

    def get_wrapper(self, workspace_root: str | Path | None = None) -> LSPServerWrapper:
        root = canonical_workspace_root(workspace_root)
        with self._lock:
            if (state := self._wrappers.get(root)) is None:
                state = _WrapperState(wrapper=LSPServerWrapper(workspace_root=root))
                self._wrappers[root] = state
            state.last_used_at = time.monotonic()
            return state.wrapper

    def shutdown(self, workspace_root: str | Path | None = None) -> None:
        with self._lock:
            if workspace_root is None:
                states = list(self._wrappers.values())
                self._wrappers.clear()
            else:
                root = canonical_workspace_root(workspace_root)
                state = self._wrappers.pop(root, None)
                states = [state] if state is not None else []

        for state in states:
            state.wrapper.shutdown()

    def clear(self) -> None:
        self.shutdown()


_wrapper_registry = LSPWrapperRegistry()


def get_lsp_wrapper(workspace_root: str | Path | None = None) -> LSPServerWrapper:
    """Get or create a workspace-scoped LSP wrapper.

    Args:
        workspace_root: Optional workspace root

    Returns:
        LSPServerWrapper instance
    """
    return _wrapper_registry.get_wrapper(workspace_root)


def shutdown_lsp_wrapper(workspace_root: str | Path | None = None) -> None:
    """Shutdown one workspace wrapper or all registered wrappers."""
    _wrapper_registry.shutdown(workspace_root)
