from __future__ import annotations

from pathlib import Path

import pytest

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState, ToolError
from vibe.core.tools.builtins.apply_patch import (
    ApplyPatch,
    ApplyPatchArgs,
    ApplyPatchConfig,
)


@pytest.fixture
def apply_patch_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ApplyPatch:
    monkeypatch.chdir(tmp_path)
    return ApplyPatch(config=ApplyPatchConfig(), state=BaseToolState())


@pytest.mark.asyncio
async def test_apply_patch_adds_new_file(
    apply_patch_tool: ApplyPatch, tmp_path: Path
) -> None:
    patch = """
*** Begin Patch
*** Add File: created.txt
+hello
+world
*** End Patch
""".strip()

    result = await collect_result(apply_patch_tool.run(ApplyPatchArgs(input=patch)))

    assert (tmp_path / "created.txt").read_text("utf-8") == "hello\nworld"
    assert result.created_paths == [str(tmp_path / "created.txt")]
    assert result.modified_paths == []
    assert result.deleted_paths == []


@pytest.mark.asyncio
async def test_apply_patch_updates_and_moves_file_with_fuzz(
    apply_patch_tool: ApplyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "sample.py"
    source.write_text("def greet():\n    return 1\n", encoding="utf-8")
    patch = """
*** Begin Patch
*** Update File: sample.py
*** Move to: renamed.py
@@ def greet():
-  return 1
+    return 2
*** End Patch
""".strip()

    result = await collect_result(apply_patch_tool.run(ApplyPatchArgs(input=patch)))

    assert not source.exists()
    assert (tmp_path / "renamed.py").read_text(
        "utf-8"
    ) == "def greet():\n    return 2\n"
    assert result.moves[0].from_path == str(tmp_path / "sample.py")
    assert result.moves[0].to_path == str(tmp_path / "renamed.py")
    assert result.modified_paths == [str(tmp_path / "renamed.py")]
    assert result.fuzz > 0


@pytest.mark.asyncio
async def test_apply_patch_deletes_file(
    apply_patch_tool: ApplyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "obsolete.txt"
    target.write_text("remove me", encoding="utf-8")
    patch = """
*** Begin Patch
*** Delete File: obsolete.txt
*** End Patch
""".strip()

    result = await collect_result(apply_patch_tool.run(ApplyPatchArgs(input=patch)))

    assert not target.exists()
    assert result.deleted_paths == [str(target)]


@pytest.mark.asyncio
async def test_apply_patch_rejects_invalid_patch(apply_patch_tool: ApplyPatch) -> None:
    with pytest.raises(ToolError, match="Patch must start"):
        await collect_result(
            apply_patch_tool.run(ApplyPatchArgs(input="*** Update File: foo.py"))
        )


@pytest.mark.asyncio
async def test_apply_patch_reports_missing_context(
    apply_patch_tool: ApplyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "app.py"
    target.write_text("print('hello')\n", encoding="utf-8")
    patch = """
*** Begin Patch
*** Update File: app.py
@@
-print('goodbye')
+print('hello')
*** End Patch
""".strip()

    with pytest.raises(ToolError, match="Invalid Context"):
        await collect_result(apply_patch_tool.run(ApplyPatchArgs(input=patch)))
