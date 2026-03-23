from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from pathlib import Path
import shutil

import pytest

import vibe.core.tools.builtins.find_referencing_symbols as find_referencing_symbols_tool
import vibe.core.tools.builtins.find_symbol as find_symbol_tool
import vibe.core.tools.builtins.insert_after_symbol as insert_after_symbol_tool
import vibe.core.tools.builtins.insert_before_symbol as insert_before_symbol_tool
import vibe.core.tools.builtins.rename_symbol as rename_symbol_tool
import vibe.core.tools.builtins.replace_symbol_body as replace_symbol_body_tool
from vibe.core.tools.base import InvokeContext, ToolError, ToolPermission
from vibe.core.tools.builtins._lsp_symbol_tool_utils import apply_workspace_edit
from vibe.core.tools.builtins.find_referencing_symbols import (
    FindReferencingSymbols,
    FindReferencingSymbolsConfig,
)
from vibe.core.tools.builtins.find_symbol import FindSymbol, FindSymbolConfig
from vibe.core.tools.builtins.insert_after_symbol import (
    InsertAfterSymbol,
    InsertAfterSymbolConfig,
)
from vibe.core.tools.builtins.insert_before_symbol import (
    InsertBeforeSymbol,
    InsertBeforeSymbolConfig,
)
from vibe.core.tools.builtins.rename_symbol import RenameSymbol, RenameSymbolConfig
from vibe.core.tools.builtins.replace_symbol_body import (
    ReplaceSymbolBody,
    ReplaceSymbolBodyConfig,
)
from vibe.core.tools.lsp.ls_config import Language
from vibe.core.tools.lsp.symbol import Symbol, SymbolKind
from vibe.core.tools.lsp.wrapper import LSPServerWrapper


def _build_symbol(
    file_path: Path,
    *,
    name: str = "target",
    kind: SymbolKind = SymbolKind.FUNCTION,
    start_line: int = 0,
    start_character: int = 0,
    end_line: int = 1,
    end_character: int = 8,
) -> Symbol:
    return Symbol(
        name=name,
        kind=kind,
        file_path=str(file_path),
        start_line=start_line,
        start_character=start_character,
        end_line=end_line,
        end_character=end_character,
    )


async def _invoke_tool(tool, **kwargs):
    result = None
    async for item in tool.invoke(**kwargs):
        result = item
    assert result is not None
    return result


class _FakeRetriever:
    def __init__(
        self,
        *,
        symbols: list[Symbol] | None = None,
        references: list[dict[str, object]] | None = None,
        workspace_edit: dict[str, list[dict[str, object]]] | None = None,
    ) -> None:
        self._symbols = symbols or []
        self._references = references or []
        self._workspace_edit = workspace_edit

    def find_symbol(self, pattern: str, file_path: str | None = None) -> list[Symbol]:
        del pattern, file_path
        return self._symbols

    def find_references(
        self,
        file_path: str,
        line: int,
        character: int,
        include_declaration: bool = True,
    ) -> list[dict[str, object]]:
        del file_path, line, character, include_declaration
        return self._references

    def rename_symbol_by_name(
        self, symbol_name: str, file_path: str, new_name: str
    ) -> dict[str, list[dict[str, object]]] | None:
        del symbol_name, file_path, new_name
        return self._workspace_edit


class _FakeWrapper:
    def __init__(self, diagnostics: dict[str, list[dict[str, object]]] | None = None):
        self._diagnostics = diagnostics or {}

    def get_diagnostics(self, file_path: str) -> list[dict[str, object]]:
        return self._diagnostics.get(file_path, [])

    def get_position_encoding(self, file_path: str | Path) -> str:
        del file_path
        return "utf-16"


class _FakeWorkspaceServer:
    def __init__(self, symbols: list[dict[str, object]]) -> None:
        self._symbols = symbols

    def request_workspace_symbol(self, query: str) -> list[dict[str, object]]:
        del query
        return self._symbols


class _FakeReferenceServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int, bool]] = []

    def request_references(
        self,
        relative_file_path: str,
        line: int,
        character: int,
        include_declaration: bool = False,
    ) -> list[dict[str, object]]:
        self.calls.append(
            (relative_file_path, line, character, include_declaration)
        )
        return []


@pytest.fixture(autouse=True)
def _cleanup_lsp_wrapper() -> Iterator[None]:
    yield
    from vibe.core.tools.lsp.wrapper import shutdown_lsp_wrapper

    shutdown_lsp_wrapper()


@pytest.mark.asyncio
async def test_find_symbol_returns_structured_matches(
    tmp_working_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_working_directory / "sample.py"
    file_path.write_text("def target():\n    return 1\n", encoding="utf-8")
    symbol = _build_symbol(file_path, name="target", end_character=12)

    monkeypatch.setattr(
        find_symbol_tool,
        "get_retriever_and_wrapper",
        lambda file_path=None, workspace_root=None: (
            _FakeRetriever(symbols=[symbol]),
            object(),
        ),
    )

    tool = FindSymbol.from_config(FindSymbolConfig())
    result = await _invoke_tool(tool, symbol_name="target", file_path=str(file_path))

    assert result.symbols
    assert result.symbols[0].name == "target"
    assert result.symbols[0].file_path == str(file_path)
    assert "Found 1 symbol" in result.summary


@pytest.mark.asyncio
async def test_find_symbol_rejects_unsupported_extension(
    tmp_working_directory: Path,
) -> None:
    file_path = tmp_working_directory / "notes.txt"
    file_path.write_text("plain text only\n", encoding="utf-8")

    tool = FindSymbol.from_config(FindSymbolConfig())
    with pytest.raises(ToolError, match="No LSP server is configured"):
        await _invoke_tool(tool, symbol_name="notes", file_path=str(file_path))


@pytest.mark.asyncio
async def test_find_referencing_symbols_returns_empty_when_symbol_missing(
    tmp_working_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_working_directory / "sample.py"
    file_path.write_text("value = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        find_referencing_symbols_tool,
        "get_retriever_and_wrapper",
        lambda file_path=None, workspace_root=None: (
            _FakeRetriever(symbols=[]),
            object(),
        ),
    )

    tool = FindReferencingSymbols.from_config(FindReferencingSymbolsConfig())
    result = await _invoke_tool(
        tool, symbol_name="missing", file_path=str(file_path), include_declaration=False
    )

    assert result.references == []
    assert result.file_count == 0
    assert "No symbol named 'missing'" in result.summary


def test_rename_symbol_permission_escalates_for_outside_workspace(
    tmp_working_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inside_path = tmp_working_directory / "inside.py"
    outside_path = tmp_working_directory.parent / "outside.py"
    monkeypatch.setattr(
        rename_symbol_tool,
        "preview_rename_paths",
        lambda **kwargs: [inside_path, outside_path],
    )

    tool = RenameSymbol.from_config(
        RenameSymbolConfig(permission=ToolPermission.ALWAYS)
    )
    permission = tool.resolve_permission(
        rename_symbol_tool.RenameSymbolArgs(
            symbol_name="target",
            file_path=str(inside_path),
            new_name="renamed",
        )
    )

    assert permission is ToolPermission.ASK


@pytest.mark.asyncio
async def test_rename_symbol_applies_multi_file_edit_and_reports_diagnostics(
    tmp_working_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path = tmp_working_directory / "source.py"
    consumer_path = tmp_working_directory / "consumer.py"
    source_path.write_text("def target():\n    return 1\n", encoding="utf-8")
    consumer_path.write_text("value = target()\n", encoding="utf-8")

    symbol = _build_symbol(source_path, name="target", end_character=12)
    workspace_edit = {
        str(source_path): [
            {
                "start_line": 0,
                "start_character": 4,
                "end_line": 0,
                "end_character": 10,
                "new_text": "renamed",
            }
        ],
        str(consumer_path): [
            {
                "start_line": 0,
                "start_character": 8,
                "end_line": 0,
                "end_character": 14,
                "new_text": "renamed",
            }
        ],
    }
    wrapper = _FakeWrapper(
        diagnostics={
            str(source_path): [
                {
                    "severity": "Error",
                    "message": "sample diagnostic",
                    "line": 1,
                    "character": 0,
                }
            ]
        }
    )
    monkeypatch.setattr(
        rename_symbol_tool,
        "get_retriever_and_wrapper",
        lambda file_path=None, workspace_root=None: (
            _FakeRetriever(symbols=[symbol], workspace_edit=workspace_edit),
            wrapper,
        ),
    )

    tool = RenameSymbol.from_config(RenameSymbolConfig())
    result = await _invoke_tool(
        tool,
        symbol_name="target",
        file_path=str(source_path),
        new_name="renamed",
    )

    assert result.applied is True
    assert result.total_changes == 2
    assert len(result.changed_files) == 2
    assert result.diagnostics[0].message == "sample diagnostic"
    assert "renamed" in source_path.read_text(encoding="utf-8")
    assert "renamed" in consumer_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_replace_symbol_body_updates_python_body(
    tmp_working_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_working_directory / "sample.py"
    file_path.write_text(
        "def target():\n    return 1\n\n\ndef other():\n    return 2\n",
        encoding="utf-8",
    )
    symbol = _build_symbol(file_path, name="target", end_line=1, end_character=12)
    monkeypatch.setattr(
        replace_symbol_body_tool,
        "get_retriever_and_wrapper",
        lambda file_path=None, workspace_root=None: (
            _FakeRetriever(symbols=[symbol]),
            _FakeWrapper(),
        ),
    )

    tool = ReplaceSymbolBody.from_config(ReplaceSymbolBodyConfig())
    result = await _invoke_tool(
        tool,
        symbol_name="target",
        file_path=str(file_path),
        new_body="return 41",
        preserve_signature=True,
    )

    assert result.applied is True
    assert "return 41" in file_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_replace_symbol_body_updates_brace_language_body(
    tmp_working_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_working_directory / "sample.go"
    file_path.write_text(
        "package main\n\nfunc target() int {\n    return 1\n}\n",
        encoding="utf-8",
    )
    symbol = _build_symbol(
        file_path, name="target", start_line=2, end_line=4, end_character=1
    )
    monkeypatch.setattr(
        replace_symbol_body_tool,
        "get_retriever_and_wrapper",
        lambda file_path=None, workspace_root=None: (
            _FakeRetriever(symbols=[symbol]),
            _FakeWrapper(),
        ),
    )

    tool = ReplaceSymbolBody.from_config(ReplaceSymbolBodyConfig())
    result = await _invoke_tool(
        tool,
        symbol_name="target",
        file_path=str(file_path),
        new_body="return 41",
        preserve_signature=True,
    )

    assert result.applied is True
    assert "func target() int {" in file_path.read_text(encoding="utf-8")
    assert "return 41" in file_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_replace_symbol_body_surfaces_server_start_failure(
    tmp_working_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_working_directory / "sample.py"
    file_path.write_text("def target():\n    return 1\n", encoding="utf-8")

    def _raise_server_failed(
        file_path: Path | None = None,
        workspace_root: Path | None = None,
    ) -> tuple[_FakeRetriever, _FakeWrapper]:
        del file_path, workspace_root
        raise ToolError("server failed")

    monkeypatch.setattr(
        replace_symbol_body_tool,
        "get_retriever_and_wrapper",
        _raise_server_failed,
    )

    tool = ReplaceSymbolBody.from_config(ReplaceSymbolBodyConfig())
    with pytest.raises(ToolError, match="server failed"):
        await _invoke_tool(
            tool,
            symbol_name="target",
            file_path=str(file_path),
            new_body="return 2",
        )


@pytest.mark.asyncio
async def test_insert_before_symbol_inserts_content(
    tmp_working_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_working_directory / "sample.py"
    file_path.write_text("def target():\n    return 1\n", encoding="utf-8")
    symbol = _build_symbol(file_path, name="target", end_character=12)
    monkeypatch.setattr(
        insert_before_symbol_tool,
        "get_retriever_and_wrapper",
        lambda file_path=None, workspace_root=None: (
            _FakeRetriever(symbols=[symbol]),
            _FakeWrapper(),
        ),
    )

    tool = InsertBeforeSymbol.from_config(InsertBeforeSymbolConfig())
    result = await _invoke_tool(
        tool,
        symbol_name="target",
        file_path=str(file_path),
        content="def helper():\n    return 0",
    )

    assert result.applied is True
    content = file_path.read_text(encoding="utf-8")
    assert content.startswith("def helper():")


@pytest.mark.asyncio
async def test_insert_after_symbol_inserts_content(
    tmp_working_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_working_directory / "sample.py"
    file_path.write_text("def target():\n    return 1\n", encoding="utf-8")
    symbol = _build_symbol(file_path, name="target", end_character=12)
    monkeypatch.setattr(
        insert_after_symbol_tool,
        "get_retriever_and_wrapper",
        lambda file_path=None, workspace_root=None: (
            _FakeRetriever(symbols=[symbol]),
            _FakeWrapper(),
        ),
    )

    tool = InsertAfterSymbol.from_config(InsertAfterSymbolConfig())
    result = await _invoke_tool(
        tool,
        symbol_name="target",
        file_path=str(file_path),
        content="def helper():\n    return 0",
    )

    assert result.applied is True
    content = file_path.read_text(encoding="utf-8")
    assert "def helper():" in content
    assert content.index("def target():") < content.index("def helper():")


@pytest.mark.asyncio
async def test_find_symbol_uses_context_workspace_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current_workspace = tmp_path / "current"
    current_workspace.mkdir()
    other_workspace = tmp_path / "other"
    other_workspace.mkdir()
    file_path = other_workspace / "pkg" / "sample.py"
    file_path.parent.mkdir()
    file_path.write_text("def target():\n    return 1\n", encoding="utf-8")
    symbol = _build_symbol(file_path, name="target", end_character=12)
    observed: dict[str, object] = {}

    monkeypatch.chdir(current_workspace)

    def _fake_backend(
        file_path: Path | None = None,
        workspace_root: Path | None = None,
    ) -> tuple[_FakeRetriever, object]:
        observed["file_path"] = file_path
        observed["workspace_root"] = workspace_root
        return _FakeRetriever(symbols=[symbol]), object()

    monkeypatch.setattr(find_symbol_tool, "get_retriever_and_wrapper", _fake_backend)

    tool = FindSymbol.from_config(FindSymbolConfig())
    result = await _invoke_tool(
        tool,
        symbol_name="target",
        file_path="pkg/sample.py",
        ctx=InvokeContext(
            tool_call_id="tool-call",
            workspace_root=other_workspace,
        ),
    )

    assert result.file_path == str(file_path)
    assert observed["file_path"] == file_path.resolve()
    assert observed["workspace_root"] == other_workspace.resolve()


def test_get_lsp_wrapper_is_workspace_keyed(tmp_path: Path) -> None:
    from vibe.core.tools.lsp.wrapper import get_lsp_wrapper

    workspace_one = tmp_path / "workspace-one"
    workspace_one.mkdir()
    workspace_two = tmp_path / "workspace-two"
    workspace_two.mkdir()

    wrapper_one = get_lsp_wrapper(workspace_one)
    wrapper_two = get_lsp_wrapper(workspace_two)

    assert wrapper_one is not wrapper_two
    assert wrapper_one.workspace_root == workspace_one.resolve()
    assert wrapper_two.workspace_root == workspace_two.resolve()


def test_apply_workspace_edit_preserves_crlf_and_utf16_offsets(
    tmp_working_directory: Path,
) -> None:
    file_path = tmp_working_directory / "sample.py"
    file_path.write_bytes("value = 'a𐐀b'\r\n".encode("utf-8"))

    changed_files, skipped_files, total_changes = apply_workspace_edit(
        {
            str(file_path): [
                {
                    "start_line": 0,
                    "start_character": 10,
                    "end_line": 0,
                    "end_character": 12,
                    "new_text": "X",
                }
            ]
        },
        workspace_root=tmp_working_directory,
        position_encoding="utf-16",
    )

    assert total_changes == 1
    assert skipped_files == []
    assert changed_files[0].file_path == str(file_path)
    assert file_path.read_bytes() == "value = 'aXb'\r\n".encode("utf-8")


@pytest.mark.asyncio
async def test_replace_symbol_body_handles_python_non_ascii_offsets(
    tmp_working_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_working_directory / "sample.py"
    file_path.write_text('def target():\n    return "café"\n', encoding="utf-8")
    symbol = _build_symbol(file_path, name="target", end_line=1, end_character=17)

    monkeypatch.setattr(
        replace_symbol_body_tool,
        "get_retriever_and_wrapper",
        lambda file_path=None, workspace_root=None: (
            _FakeRetriever(symbols=[symbol]),
            _FakeWrapper(),
        ),
    )

    tool = ReplaceSymbolBody.from_config(ReplaceSymbolBodyConfig())
    result = await _invoke_tool(
        tool,
        symbol_name="target",
        file_path=str(file_path),
        new_body='return "naïve"',
        preserve_signature=True,
    )

    assert result.applied is True
    assert 'return "naïve"' in file_path.read_text(encoding="utf-8")


def test_workspace_symbol_search_discovers_other_languages(
    tmp_working_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    go_path = tmp_working_directory / "main.go"
    go_path.write_text("package main\n\nfunc greet() {}\n", encoding="utf-8")
    wrapper = LSPServerWrapper(workspace_root=tmp_working_directory)
    requested_languages: list[Language] = []
    server = _FakeWorkspaceServer([
        {
            "name": "greet",
            "kind": int(SymbolKind.FUNCTION),
            "range": {
                "start": {"line": 2, "character": 0},
                "end": {"line": 2, "character": 12},
            },
            "location": {
                "absolutePath": str(go_path),
                "uri": go_path.as_uri(),
                "relativePath": "main.go",
                "range": {
                    "start": {"line": 2, "character": 0},
                    "end": {"line": 2, "character": 12},
                },
            },
        }
    ])

    def fake_get_server(language: Language):
        requested_languages.append(language)
        if language is Language.GO:
            return server
        return None

    monkeypatch.setattr(wrapper, "get_server", fake_get_server)

    symbols = wrapper.get_workspace_symbols("greet")

    assert [symbol.name for symbol in symbols] == ["greet"]
    assert Language.GO in requested_languages
    assert Language.PYTHON not in requested_languages


def test_wrapper_forwards_include_declaration_to_language_server(
    tmp_working_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_working_directory / "sample.py"
    file_path.write_text("def target():\n    return 1\n", encoding="utf-8")
    wrapper = LSPServerWrapper(workspace_root=tmp_working_directory)
    server = _FakeReferenceServer()

    monkeypatch.setattr(wrapper, "get_server_for_file", lambda path: server)

    wrapper.find_references(file_path, 0, 4, include_declaration=False)

    assert server.calls == [("sample.py", 0, 4, False)]


@pytest.mark.asyncio
@pytest.mark.timeout(60)
@pytest.mark.skipif(
    importlib.util.find_spec("pyright") is None,
    reason="pyright is not installed",
)
async def test_python_lsp_smoke_find_symbol_and_references(
    tmp_working_directory: Path,
) -> None:
    main_path = tmp_working_directory / "main.py"
    main_path.write_text(
        "def greet() -> str:\n    return 'hi'\n\n\nvalue = greet()\n",
        encoding="utf-8",
    )

    find_tool = FindSymbol.from_config(FindSymbolConfig())
    find_result = await _invoke_tool(
        find_tool, symbol_name="greet", file_path=str(main_path)
    )

    refs_tool = FindReferencingSymbols.from_config(FindReferencingSymbolsConfig())
    refs_result = await _invoke_tool(
        refs_tool,
        symbol_name="greet",
        file_path=str(main_path),
        include_declaration=True,
    )

    assert any(symbol.name == "greet" for symbol in find_result.symbols)
    assert refs_result.symbol_name == "greet"
    assert refs_result.file_path == str(main_path)
    assert refs_result.summary.startswith("Found ")


@pytest.mark.asyncio
@pytest.mark.timeout(120)
@pytest.mark.skipif(
    shutil.which("node") is None or shutil.which("npm") is None,
    reason="node and npm are required for TypeScript LSP tests",
)
async def test_typescript_lsp_smoke_find_symbol_and_rename(
    tmp_working_directory: Path,
) -> None:
    if shutil.which("node") is None or shutil.which("npm") is None:
        pytest.skip("node and npm are required for TypeScript LSP tests")

    source_path = tmp_working_directory / "main.ts"
    consumer_path = tmp_working_directory / "consumer.ts"
    source_path.write_text("export function greet(): string {\n  return 'hi';\n}\n", encoding="utf-8")
    consumer_path.write_text(
        "import { greet } from './main';\n\nexport const value = greet();\n",
        encoding="utf-8",
    )

    find_tool = FindSymbol.from_config(FindSymbolConfig())
    find_result = await _invoke_tool(
        find_tool, symbol_name="greet", file_path=str(source_path)
    )

    rename_tool = RenameSymbol.from_config(
        RenameSymbolConfig(permission=ToolPermission.ALWAYS)
    )
    rename_result = await _invoke_tool(
        rename_tool,
        symbol_name="greet",
        file_path=str(source_path),
        new_name="welcome",
    )

    assert any(symbol.name == "greet" for symbol in find_result.symbols)
    assert rename_result.applied is True
    assert "welcome" in source_path.read_text(encoding="utf-8")
    assert "welcome" in consumer_path.read_text(encoding="utf-8")
