from __future__ import annotations

import ast
from collections.abc import Iterable
import importlib.util
from pathlib import Path
import shutil
import textwrap
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from vibe.core.tools.base import InvokeContext, ToolError, ToolPermission
from vibe.core.tools.builtins._file_tool_utils import (
    ensure_existing_file,
    resolve_tool_path,
)
from vibe.core.tools.lsp.text_document import (
    InvalidTextLocationError,
    LoadedTextDocument,
    count_position_units,
    index_to_position,
    position_to_index,
)
from vibe.core.tools.utils import resolve_file_tool_permission
from vibe.core.workspace import canonical_workspace_root, workspace_root_from_context

if TYPE_CHECKING:
    from vibe.core.tools.lsp.ls_config import Language
    from vibe.core.tools.lsp.symbol import Symbol

_BRACE_BODY_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".cxx",
    ".dart",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".mjs",
    ".php",
    ".rs",
    ".sc",
    ".scala",
    ".swift",
    ".ts",
    ".tsx",
}


class SymbolMatch(BaseModel):
    name: str
    name_path: str
    kind: str
    file_path: str
    line: int
    start_character: int
    end_line: int
    end_character: int
    preview: str | None = None


class ReferenceMatch(BaseModel):
    file_path: str
    line: int
    character: int
    end_line: int
    end_character: int
    line_text: str | None = None


class DiagnosticMatch(BaseModel):
    file_path: str
    severity: str
    message: str
    line: int
    character: int


class FileChange(BaseModel):
    file_path: str
    change_count: int = Field(ge=0)


class TextRange(BaseModel):
    start_line: int = Field(ge=1)
    start_character: int = Field(ge=0)
    end_line: int = Field(ge=1)
    end_character: int = Field(ge=0)


class InsertOperationResult(BaseModel):
    file_path: str
    insert_line: int = Field(ge=1)
    inserted_range: TextRange


class ReplaceOperationResult(BaseModel):
    file_path: str
    replaced_range: TextRange


class _EditRange(BaseModel):
    start_line: int
    start_character: int
    end_line: int
    end_character: int


def workspace_root(ctx: InvokeContext | None = None) -> Path:
    return workspace_root_from_context(ctx)


def resolve_workspace_file(
    path_str: str,
    *,
    workspace_root: Path | None = None,
) -> Path:
    root = canonical_workspace_root(workspace_root)
    path = ensure_workspace_path(
        resolve_tool_path(path_str, base_dir=root),
        workspace_root=root,
    )
    return ensure_existing_file(path)


def ensure_workspace_path(path: Path, *, workspace_root: Path | None = None) -> Path:
    root = canonical_workspace_root(workspace_root)
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolError(
            f"Path '{resolved}' is outside the current workspace '{root}'"
        ) from exc
    return resolved


def relative_path_display(path: Path, *, workspace_root: Path | None = None) -> str:
    root = canonical_workspace_root(workspace_root)
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def resolve_mutation_permission(
    paths: Iterable[Path],
    *,
    allowlist: list[str],
    denylist: list[str],
    config_permission: ToolPermission,
) -> ToolPermission | None:
    unique_paths = list(dict.fromkeys(path.resolve(strict=False) for path in paths))
    if not unique_paths:
        return None

    saw_always = False
    saw_ask = False
    saw_default = False
    for path in unique_paths:
        permission = resolve_file_tool_permission(
            str(path),
            allowlist=allowlist,
            denylist=denylist,
            config_permission=config_permission,
        )
        match permission:
            case ToolPermission.NEVER:
                return ToolPermission.NEVER
            case ToolPermission.ASK:
                saw_ask = True
            case ToolPermission.ALWAYS:
                saw_always = True
            case _:
                saw_default = True

    if saw_ask:
        return ToolPermission.ASK
    if saw_always and not saw_default:
        return ToolPermission.ALWAYS
    return None


def build_symbol_match(symbol: Symbol, *, include_preview: bool = True) -> SymbolMatch:
    preview = _build_symbol_preview(symbol) if include_preview else None
    file_path = Path(symbol.file_path).resolve(strict=False)
    return SymbolMatch(
        name=symbol.name,
        name_path=symbol.name_path,
        kind=symbol.kind_name,
        file_path=str(file_path),
        line=symbol.line_number,
        start_character=symbol.start_character,
        end_line=symbol.end_line + 1,
        end_character=symbol.end_character,
        preview=preview,
    )


def build_reference_matches(
    references: list[dict[str, Any]],
    *,
    include_declaration: bool,
    declaration_symbol: Symbol | None,
    workspace_root: Path | None = None,
) -> list[ReferenceMatch]:
    matches: list[ReferenceMatch] = []
    for reference in references:
        raw_file = reference.get("file")
        if not isinstance(raw_file, str) or not raw_file:
            continue

        try:
            path = ensure_workspace_path(Path(raw_file), workspace_root=workspace_root)
        except ToolError:
            continue

        line = int(reference.get("line", 0))
        character = int(reference.get("character", 0))
        end_line = int(reference.get("end_line", line))
        end_character = int(reference.get("end_character", character))

        if (
            not include_declaration
            and declaration_symbol is not None
            and path == Path(declaration_symbol.file_path).resolve(strict=False)
            and line == declaration_symbol.line_number
            and character == declaration_symbol.start_character
        ):
            continue

        matches.append(
            ReferenceMatch(
                file_path=str(path),
                line=line,
                character=character,
                end_line=end_line,
                end_character=end_character,
                line_text=_read_line_excerpt(path, line),
            )
        )

    return matches


def build_diagnostics(wrapper: Any, paths: Iterable[Path]) -> list[DiagnosticMatch]:
    diagnostics: list[DiagnosticMatch] = []
    for path in dict.fromkeys(path.resolve(strict=False) for path in paths):
        for diagnostic in wrapper.get_diagnostics(str(path)):
            diagnostics.append(
                DiagnosticMatch(
                    file_path=str(path),
                    severity=str(diagnostic.get("severity", "Error")),
                    message=str(diagnostic.get("message", "")),
                    line=int(diagnostic.get("line", 0)),
                    character=int(diagnostic.get("character", 0)),
                )
            )
    return diagnostics


def get_retriever_and_wrapper(
    file_path: Path | None = None,
    *,
    workspace_root: Path | None = None,
) -> tuple[Any, Any]:
    retriever_cls, get_wrapper, get_language_from_path = _load_lsp_backend()
    root = canonical_workspace_root(workspace_root)
    wrapper = get_wrapper(root)
    if file_path is not None:
        language = _ensure_runtime_dependencies(file_path, get_language_from_path)
        if wrapper.get_server_for_file(file_path) is None:
            error_detail = wrapper.get_last_startup_error(language)
            if error_detail:
                raise ToolError(
                    f"Failed to start the {language.value} language server for "
                    f"'{relative_path_display(file_path, workspace_root=root)}': {error_detail}"
                )
            raise ToolError(
                f"Failed to start the {language.value} language server for "
                f"'{relative_path_display(file_path, workspace_root=root)}'"
            )
    return retriever_cls(workspace_root=root), wrapper


def resolve_local_edit_paths(
    workspace_edit: dict[str, list[dict[str, Any]]] | None,
    *,
    workspace_root: Path | None = None,
) -> tuple[list[Path], list[str]]:
    if not workspace_edit:
        return [], []

    local_paths: list[Path] = []
    skipped_paths: list[str] = []
    for raw_path in workspace_edit:
        try:
            local_paths.append(
                ensure_workspace_path(Path(raw_path), workspace_root=workspace_root)
            )
        except ToolError:
            skipped_paths.append(str(raw_path))

    return list(dict.fromkeys(local_paths)), skipped_paths


def apply_workspace_edit(
    workspace_edit: dict[str, list[dict[str, Any]]],
    *,
    workspace_root: Path | None = None,
    position_encoding: str | None = None,
) -> tuple[list[FileChange], list[str], int]:
    changed_files: list[FileChange] = []
    skipped_paths: list[str] = []
    total_changes = 0

    for raw_path, edits in workspace_edit.items():
        try:
            path = ensure_workspace_path(Path(raw_path), workspace_root=workspace_root)
        except ToolError:
            skipped_paths.append(str(raw_path))
            continue

        file_path = ensure_existing_file(path)
        document = LoadedTextDocument.read(
            file_path, position_encoding=position_encoding
        )
        updated = document.text
        sorted_edits = sorted(
            edits,
            key=lambda edit: (
                int(edit.get("start_line", 0)),
                int(edit.get("start_character", 0)),
                int(edit.get("end_line", 0)),
                int(edit.get("end_character", 0)),
            ),
            reverse=True,
        )
        for edit in sorted_edits:
            updated = _apply_text_edit(
                document,
                updated_text=updated,
                start_line=int(edit.get("start_line", 0)),
                start_character=int(edit.get("start_character", 0)),
                end_line=int(edit.get("end_line", 0)),
                end_character=int(edit.get("end_character", 0)),
                new_text=str(edit.get("new_text", "")),
            )

        if updated == document.text:
            continue

        document.write(updated)
        change_count = len(sorted_edits)
        total_changes += change_count
        changed_files.append(
            FileChange(file_path=str(file_path), change_count=change_count)
        )

    return changed_files, skipped_paths, total_changes


def preview_rename_paths(
    *,
    symbol_name: str,
    file_path: str,
    new_name: str,
    workspace_root: Path | None = None,
) -> list[Path]:
    try:
        resolved_root = canonical_workspace_root(workspace_root)
        resolved_file = resolve_workspace_file(file_path, workspace_root=resolved_root)
        retriever, _ = get_retriever_and_wrapper(
            resolved_file, workspace_root=resolved_root
        )
        workspace_edit = retriever.rename_symbol_by_name(
            symbol_name, str(resolved_file), new_name
        )
        local_paths, _ = resolve_local_edit_paths(
            workspace_edit, workspace_root=resolved_root
        )
        return local_paths or [resolved_file]
    except ToolError:
        return []


def find_target_symbol(
    retriever: Any,
    *,
    symbol_name: str,
    file_path: Path,
) -> Any | None:
    symbols = retriever.find_symbol(symbol_name, str(file_path))
    return symbols[0] if symbols else None


def replace_symbol_body_in_file(
    *,
    file_path: Path,
    symbol: Symbol,
    new_body: str,
    preserve_signature: bool,
    position_encoding: str | None = None,
) -> ReplaceOperationResult:
    document = LoadedTextDocument.read(
        file_path, position_encoding=position_encoding
    )
    original = document.text
    replacement_range = _replacement_range_for_symbol(
        text=original,
        symbol=symbol,
        file_path=file_path,
        preserve_signature=preserve_signature,
        position_encoding=position_encoding,
    )

    if preserve_signature:
        indent = _derive_child_indent(
            original,
            symbol_start_line=symbol.start_line,
            body_start_line=replacement_range.start_line,
        )
        replacement_text = _format_indented_block(
            new_body,
            indent=indent,
            prefix_newline=replacement_range.start_line == symbol.start_line,
            suffix_newline=True,
        )
    else:
        normalized = textwrap.dedent(new_body).strip("\n")
        replacement_text = normalized
        if (
            symbol.start_line != symbol.end_line
            and normalized
            and not normalized.endswith("\n")
        ):
            replacement_text += "\n"

    updated = _apply_text_edit(
        document,
        updated_text=original,
        start_line=replacement_range.start_line,
        start_character=replacement_range.start_character,
        end_line=replacement_range.end_line,
        end_character=replacement_range.end_character,
        new_text=replacement_text,
    )
    if updated != original:
        document.write(updated)

    return ReplaceOperationResult(
        file_path=str(file_path),
        replaced_range=TextRange(
            start_line=replacement_range.start_line + 1,
            start_character=replacement_range.start_character,
            end_line=replacement_range.end_line + 1,
            end_character=replacement_range.end_character,
        ),
    )


def insert_relative_to_symbol(
    *,
    file_path: Path,
    symbol: Symbol,
    content: str,
    position: str,
    position_encoding: str | None = None,
) -> InsertOperationResult:
    document = LoadedTextDocument.read(
        file_path, position_encoding=position_encoding
    )
    original = document.text
    insertion_line = symbol.start_line if position == "before" else symbol.end_line + 1
    target_indent = _insertion_indent(
        original, insertion_line, fallback_line=symbol.start_line
    )
    insert_text = _format_indented_block(
        content,
        indent=target_indent,
        prefix_newline=False,
        suffix_newline=True,
    )
    if not insert_text.endswith("\n\n"):
        insert_text += "\n"
    if insertion_line >= _line_count(original) and original and not original.endswith(
        "\n"
    ):
        insert_text = "\n" + insert_text

    updated = _apply_text_edit(
        document,
        updated_text=original,
        start_line=insertion_line,
        start_character=0,
        end_line=insertion_line,
        end_character=0,
        new_text=insert_text,
    )
    if updated != original:
        document.write(updated)

    end_line = insertion_line + insert_text.count("\n")
    end_character = 0
    if not insert_text.endswith("\n"):
        end_character = count_position_units(insert_text.rsplit("\n", 1)[-1])

    return InsertOperationResult(
        file_path=str(file_path),
        insert_line=insertion_line + 1,
        inserted_range=TextRange(
            start_line=insertion_line + 1,
            start_character=0,
            end_line=end_line + 1,
            end_character=end_character,
        ),
    )


def _load_lsp_backend() -> tuple[Any, Any, Any]:
    try:
        from vibe.core.tools.lsp.retriever import SymbolRetriever
        from vibe.core.tools.lsp.wrapper import (
            get_language_from_path,
            get_lsp_wrapper,
        )
    except ModuleNotFoundError as exc:
        raise ToolError(
            "The native LSP backend is unavailable. Install Malibu's runtime LSP "
            "dependencies and try again."
        ) from exc

    return SymbolRetriever, get_lsp_wrapper, get_language_from_path


def _ensure_runtime_dependencies(file_path: Path, get_language_from_path: Any) -> Language:
    language = get_language_from_path(file_path)
    if language is None:
        raise ToolError(f"No LSP server is configured for '{file_path.suffix or file_path.name}'")

    match language.name:
        case "PYTHON":
            if importlib.util.find_spec("pyright") is None:
                raise ToolError("Python symbol tools require the 'pyright' package at runtime")
            return language
        case "TYPESCRIPT":
            missing = [tool for tool in ("node", "npm") if shutil.which(tool) is None]
            if missing:
                missing_tools = ", ".join(missing)
                raise ToolError(
                    f"TypeScript symbol tools require {missing_tools} to be available in PATH"
                )
            return language
        case _:
            return language


def _build_symbol_preview(symbol: Symbol) -> str | None:
    try:
        preview = symbol.get_body().strip()
    except Exception:
        return None

    if not preview:
        return None

    compact = " ".join(preview.split())
    if len(compact) <= 200:
        return compact
    return f"{compact[:197]}..."


def _read_line_excerpt(path: Path, line_number: int) -> str | None:
    try:
        lines = LoadedTextDocument.read(path).text.splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    index = line_number - 1
    if 0 <= index < len(lines):
        excerpt = lines[index].strip()
        if len(excerpt) <= 160:
            return excerpt
        return f"{excerpt[:157]}..."
    return None


def _replacement_range_for_symbol(
    *,
    text: str,
    symbol: Symbol,
    file_path: Path,
    preserve_signature: bool,
    position_encoding: str | None = None,
) -> _EditRange:
    if not preserve_signature:
        return _EditRange(
            start_line=symbol.start_line,
            start_character=symbol.start_character,
            end_line=symbol.end_line,
            end_character=symbol.end_character,
        )

    match file_path.suffix.lower():
        case ".py" | ".pyi":
            return _python_body_range(
                text,
                symbol,
                position_encoding=position_encoding,
            )
        case suffix if suffix in _BRACE_BODY_SUFFIXES:
            return _brace_language_body_range(
                text,
                symbol,
                file_path=file_path,
                position_encoding=position_encoding,
            )
        case suffix:
            raise ToolError(
                "replace_symbol_body currently supports preserve_signature=True "
                "for Python and brace-delimited languages, "
                f"not '{suffix or file_path.name}'"
            )


def _python_body_range(
    text: str,
    symbol: Symbol,
    *,
    position_encoding: str | None = None,
) -> _EditRange:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise ToolError(f"Could not parse Python file for symbol body replacement: {exc}") from exc

    node = _find_python_symbol_node(tree, symbol)
    if node is None or not getattr(node, "body", None):
        raise ToolError(
            f"Could not identify the Python body for symbol '{symbol.name_path}' safely"
        )

    first_stmt = node.body[0]
    last_stmt = node.body[-1]
    end_lineno = getattr(last_stmt, "end_lineno", None)
    end_col_offset = getattr(last_stmt, "end_col_offset", None)
    if end_lineno is None or end_col_offset is None:
        raise ToolError(
            f"Could not identify the Python body for symbol '{symbol.name_path}' safely"
        )

    return _EditRange(
        start_line=first_stmt.lineno - 1,
        start_character=_python_ast_col_to_position_character(
            text,
            line=first_stmt.lineno - 1,
            utf8_offset=first_stmt.col_offset,
            position_encoding=position_encoding,
        ),
        end_line=end_lineno - 1,
        end_character=_python_ast_col_to_position_character(
            text,
            line=end_lineno - 1,
            utf8_offset=end_col_offset,
            position_encoding=position_encoding,
        ),
    )


def _find_python_symbol_node(
    tree: ast.AST, symbol: Symbol
) -> ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        end_lineno = getattr(node, "end_lineno", None)
        if end_lineno is None:
            continue

        if (
            node.name == symbol.name
            and node.lineno - 1 == symbol.start_line
            and end_lineno - 1 == symbol.end_line
        ):
            return node

    return None


def _python_ast_col_to_position_character(
    text: str,
    *,
    line: int,
    utf8_offset: int,
    position_encoding: str | None = None,
) -> int:
    lines = text.splitlines()
    if not 0 <= line < len(lines):
        raise ToolError("Python body range line is outside the file")

    line_text = lines[line]
    consumed_bytes = 0
    codepoint_index = 0
    while codepoint_index < len(line_text) and consumed_bytes < utf8_offset:
        consumed_bytes += len(line_text[codepoint_index].encode("utf-8"))
        codepoint_index += 1

    if consumed_bytes != utf8_offset:
        raise ToolError("Python body range splits a multi-byte character")

    return count_position_units(line_text[:codepoint_index], position_encoding)


def _brace_language_body_range(
    text: str,
    symbol: Symbol,
    *,
    file_path: Path,
    position_encoding: str | None = None,
) -> _EditRange:
    start_index = _position_to_index(
        text,
        line=symbol.start_line,
        character=symbol.start_character,
        position_encoding=position_encoding,
    )
    end_index = _position_to_index(
        text,
        line=symbol.end_line,
        character=symbol.end_character,
        position_encoding=position_encoding,
    )
    snippet = text[start_index:end_index]
    open_brace = _find_first_brace(snippet)
    if open_brace is None:
        raise ToolError(
            f"Could not identify the body for symbol '{symbol.name_path}' safely in "
            f"'{file_path.suffix or file_path.name}'"
        )

    close_brace = _find_matching_brace(snippet, open_brace)
    if close_brace is None:
        raise ToolError(
            f"Could not identify the body for symbol '{symbol.name_path}' safely in "
            f"'{file_path.suffix or file_path.name}'"
        )

    return _index_range_to_positions(
        text,
        start_index + open_brace + 1,
        start_index + close_brace,
        position_encoding=position_encoding,
    )


def _find_first_brace(snippet: str) -> int | None:
    state = "code"
    index = 0
    while index < len(snippet):
        char = snippet[index]
        next_char = snippet[index + 1] if index + 1 < len(snippet) else ""

        match state:
            case "line_comment":
                if char == "\n":
                    state = "code"
            case "block_comment":
                if char == "*" and next_char == "/":
                    state = "code"
                    index += 1
            case "single_quote":
                if char == "\\":
                    index += 1
                elif char == "'":
                    state = "code"
            case "double_quote":
                if char == "\\":
                    index += 1
                elif char == '"':
                    state = "code"
            case _:
                if char == "/" and next_char == "/":
                    state = "line_comment"
                    index += 1
                elif char == "/" and next_char == "*":
                    state = "block_comment"
                    index += 1
                elif char == "'":
                    state = "single_quote"
                elif char == '"':
                    state = "double_quote"
                elif char == "`":
                    raise ToolError(
                        "replace_symbol_body cannot safely rewrite brace-delimited "
                        "bodies that contain template literals"
                    )
                elif char == "{":
                    return index

        index += 1

    return None


def _find_matching_brace(snippet: str, open_brace: int) -> int | None:
    state = "code"
    depth = 0
    index = open_brace
    while index < len(snippet):
        char = snippet[index]
        next_char = snippet[index + 1] if index + 1 < len(snippet) else ""

        match state:
            case "line_comment":
                if char == "\n":
                    state = "code"
            case "block_comment":
                if char == "*" and next_char == "/":
                    state = "code"
                    index += 1
            case "single_quote":
                if char == "\\":
                    index += 1
                elif char == "'":
                    state = "code"
            case "double_quote":
                if char == "\\":
                    index += 1
                elif char == '"':
                    state = "code"
            case _:
                if char == "/" and next_char == "/":
                    state = "line_comment"
                    index += 1
                elif char == "/" and next_char == "*":
                    state = "block_comment"
                    index += 1
                elif char == "'":
                    state = "single_quote"
                elif char == '"':
                    state = "double_quote"
                elif char == "`":
                    raise ToolError(
                        "replace_symbol_body cannot safely rewrite brace-delimited "
                        "bodies that contain template literals"
                    )
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return index

        index += 1

    return None


def _derive_child_indent(text: str, *, symbol_start_line: int, body_start_line: int) -> str:
    lines = text.splitlines()
    if 0 <= body_start_line < len(lines):
        if indent := _leading_whitespace(lines[body_start_line]):
            return indent
    if 0 <= symbol_start_line < len(lines):
        return f"{_leading_whitespace(lines[symbol_start_line])}    "
    return "    "


def _insertion_indent(text: str, line_index: int, *, fallback_line: int) -> str:
    lines = text.splitlines()
    if 0 <= line_index < len(lines):
        return _leading_whitespace(lines[line_index])
    if 0 <= fallback_line < len(lines):
        return _leading_whitespace(lines[fallback_line])
    return ""


def _format_indented_block(
    content: str,
    *,
    indent: str,
    prefix_newline: bool,
    suffix_newline: bool,
) -> str:
    normalized = textwrap.dedent(content).strip("\n")
    lines = normalized.splitlines() or [""]
    rendered = "\n".join(f"{indent}{line}" if line else "" for line in lines)
    if prefix_newline:
        rendered = f"\n{rendered}"
    if suffix_newline and not rendered.endswith("\n"):
        rendered += "\n"
    return rendered


def _apply_text_edit(
    document: LoadedTextDocument,
    *,
    updated_text: str,
    start_line: int,
    start_character: int,
    end_line: int,
    end_character: int,
    new_text: str,
) -> str:
    current_document = LoadedTextDocument(
        path=document.path,
        text=updated_text,
        encoding=document.encoding,
        newline=document.newline,
        position_encoding=document.position_encoding,
    )
    try:
        return current_document.apply_edit(
            start_line=start_line,
            start_character=start_character,
            end_line=end_line,
            end_character=end_character,
            new_text=new_text,
        )
    except InvalidTextLocationError as exc:
        raise ToolError(str(exc)) from exc


def _position_to_index(
    text: str,
    *,
    line: int,
    character: int,
    position_encoding: str | None = None,
) -> int:
    try:
        return position_to_index(
            text,
            line=line,
            character=character,
            position_encoding=position_encoding,
        )
    except InvalidTextLocationError as exc:
        raise ToolError(str(exc)) from exc


def _index_range_to_positions(
    text: str,
    start_index: int,
    end_index: int,
    *,
    position_encoding: str | None = None,
) -> _EditRange:
    if start_index < 0 or end_index < start_index:
        raise ToolError("Invalid replacement boundary")
    start_line, start_character = _index_to_position(
        text, start_index, position_encoding=position_encoding
    )
    end_line, end_character = _index_to_position(
        text, end_index, position_encoding=position_encoding
    )
    return _EditRange(
        start_line=start_line,
        start_character=start_character,
        end_line=end_line,
        end_character=end_character,
    )


def _index_to_position(
    text: str,
    index: int,
    *,
    position_encoding: str | None = None,
) -> tuple[int, int]:
    try:
        return index_to_position(
            text,
            index,
            position_encoding=position_encoding,
        )
    except InvalidTextLocationError as exc:
        raise ToolError(str(exc)) from exc


def _line_count(text: str) -> int:
    return len(text.splitlines()) or 1


def _leading_whitespace(line: str) -> str:
    stripped = line.lstrip(" \t")
    return line[: len(line) - len(stripped)]
