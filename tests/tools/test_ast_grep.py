from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState, ToolError
from vibe.core.tools.builtins.ast_grep import AstGrep, AstGrepArgs, AstGrepConfig


@pytest.fixture
def ast_grep_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AstGrep:
    monkeypatch.chdir(tmp_path)
    return AstGrep(config=AstGrepConfig(), state=BaseToolState())


def test_ast_grep_is_unavailable_without_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert AstGrep.is_available() is False


def test_ast_grep_build_command_includes_filters(
    ast_grep_tool: AstGrep, tmp_path: Path
) -> None:
    command = ast_grep_tool._build_command(
        "ast-grep",
        AstGrepArgs(
            pattern="def $NAME($ARGS): $BODY",
            path=str(tmp_path),
            include="*.py",
            language="python",
        ),
        tmp_path,
    )

    assert command == [
        "ast-grep",
        "run",
        "--json=compact",
        "--pattern",
        "def $NAME($ARGS): $BODY",
        "--lang",
        "python",
        "--globs",
        "*.py",
        str(tmp_path),
    ]


@pytest.mark.asyncio
async def test_ast_grep_formats_matches(
    ast_grep_tool: AstGrep, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "example.py"
    source.write_text("def hello(name):\n    return name\n", encoding="utf-8")

    monkeypatch.setattr(ast_grep_tool, "_find_executable", lambda: "ast-grep")

    async def fake_execute(command: list[str]) -> list[dict[str, object]]:
        return [
            {
                "file": str(source),
                "text": "def hello(name):\n    return name",
                "range": {"start": {"line": 0}},
            }
        ]

    monkeypatch.setattr(ast_grep_tool, "_execute", fake_execute)

    result = await collect_result(
        ast_grep_tool.run(
            AstGrepArgs(pattern="def $NAME($ARGS): $BODY", path=str(tmp_path))
        )
    )

    assert str(source) in result.matches
    assert "example.py:1:" in result.matches
    assert result.match_count == 1
    assert result.was_truncated is False


@pytest.mark.asyncio
async def test_ast_grep_run_fails_when_binary_missing(
    ast_grep_tool: AstGrep, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "example.py").write_text("print('hi')\n", encoding="utf-8")

    def raise_missing() -> str:
        raise ToolError("ast-grep is not installed or not available on PATH.")

    monkeypatch.setattr(ast_grep_tool, "_find_executable", raise_missing)

    with pytest.raises(ToolError, match="ast-grep is not installed"):
        await collect_result(
            ast_grep_tool.run(AstGrepArgs(pattern="print($A)", path=str(tmp_path)))
        )
