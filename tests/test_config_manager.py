"""Tests for malibu.runtime.config_manager."""

import json
import os

import pytest

from malibu.runtime.config_manager import (
    _strip_json_comments,
    _substitute_variables,
    _deep_merge,
    load_merged_config,
)


class TestStripJsonComments:
    def test_line_comments(self) -> None:
        text = '{\n  // this is a comment\n  "key": "value"\n}'
        result = _strip_json_comments(text)
        assert "//" not in result
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_block_comments(self) -> None:
        text = '{\n  /* block comment */\n  "key": "value"\n}'
        result = _strip_json_comments(text)
        assert "/*" not in result
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_preserves_strings(self) -> None:
        text = '{"url": "https://example.com//path"}'
        result = _strip_json_comments(text)
        parsed = json.loads(result)
        assert parsed["url"] == "https://example.com//path"

    def test_empty_input(self) -> None:
        assert _strip_json_comments("") == ""


class TestSubstituteVariables:
    def test_env_substitution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR_XYZ", "hello")
        result = _substitute_variables("{env:TEST_VAR_XYZ}")
        assert result == "hello"

    def test_env_missing(self) -> None:
        result = _substitute_variables("{env:NONEXISTENT_VAR_12345}")
        assert result == ""

    def test_file_substitution(self, tmp_path: object) -> None:
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("file-content")
            f.flush()
            result = _substitute_variables(f"{{{f'file:{f.name}'}}}".replace("{{", "{").replace("}}", "}"))
        # Simpler approach:
        result = _substitute_variables(f"{{file:{f.name}}}")
        assert result == "file-content"
        os.unlink(f.name)

    def test_nested_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB_HOST", "localhost")
        data = {"db": {"host": "{env:DB_HOST}", "port": 5432}}
        result = _substitute_variables(data)
        assert result["db"]["host"] == "localhost"
        assert result["db"]["port"] == 5432

    def test_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ITEM_A", "alpha")
        result = _substitute_variables(["{env:ITEM_A}", "plain"])
        assert result == ["alpha", "plain"]

    def test_non_string_passthrough(self) -> None:
        assert _substitute_variables(42) == 42
        assert _substitute_variables(True) is True


class TestDeepMerge:
    def test_simple_override(self) -> None:
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        base = {"db": {"host": "localhost", "port": 5432}}
        override = {"db": {"host": "remote", "name": "mydb"}}
        result = _deep_merge(base, override)
        assert result == {"db": {"host": "remote", "port": 5432, "name": "mydb"}}

    def test_base_unchanged(self) -> None:
        base = {"a": 1}
        _deep_merge(base, {"a": 2})
        assert base == {"a": 1}


class TestLoadMergedConfig:
    def test_merge_order(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        import tempfile
        from pathlib import Path

        # Create a temp dir for user config
        user_dir = Path(tempfile.mkdtemp()) / ".malibu"
        user_dir.mkdir(parents=True)
        (user_dir / "settings.json").write_text(
            json.dumps({"theme": "dark", "log_level": "INFO"}),
            encoding="utf-8",
        )

        # Create project config
        project_dir = Path(tempfile.mkdtemp())
        malibu_dir = project_dir / ".malibu"
        malibu_dir.mkdir()
        (malibu_dir / "settings.json").write_text(
            json.dumps({"log_level": "DEBUG", "extra": True}),
            encoding="utf-8",
        )

        monkeypatch.setattr("malibu.runtime.config_manager.Path.home", lambda: user_dir.parent)

        result = load_merged_config(str(project_dir))
        assert result["theme"] == "dark"
        assert result["log_level"] == "DEBUG"  # project overrides user
        assert result["extra"] is True

    def test_missing_files(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        import tempfile
        from pathlib import Path

        empty_dir = Path(tempfile.mkdtemp())
        monkeypatch.setattr("malibu.runtime.config_manager.Path.home", lambda: empty_dir)
        result = load_merged_config(str(empty_dir))
        assert result == {}
