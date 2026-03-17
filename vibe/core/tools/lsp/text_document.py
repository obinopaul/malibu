from __future__ import annotations

import codecs
from dataclasses import dataclass
from pathlib import Path
import re

import charset_normalizer

from vibe.core.tools.lsp.lsp_protocol_handler.lsp_types import PositionEncodingKind

_NEWLINE_PATTERN = re.compile(r"\r\n|\r|\n")
_UTF_BOM_ENCODINGS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF16_BE, "utf-16"),
    (codecs.BOM_UTF16_LE, "utf-16"),
)


class InvalidTextLocationError(Exception):
    pass


def normalize_position_encoding(
    position_encoding: PositionEncodingKind | str | None,
) -> PositionEncodingKind:
    if position_encoding is None:
        return PositionEncodingKind.UTF16
    if isinstance(position_encoding, PositionEncodingKind):
        return position_encoding

    for candidate in PositionEncodingKind:
        if candidate.value == position_encoding:
            return candidate
    return PositionEncodingKind.UTF16


def count_position_units(
    text: str, position_encoding: PositionEncodingKind | str | None = None
) -> int:
    encoding = normalize_position_encoding(position_encoding)
    match encoding:
        case PositionEncodingKind.UTF32:
            return len(text)
        case PositionEncodingKind.UTF8:
            return len(text.encode("utf-8"))
        case PositionEncodingKind.UTF16:
            return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


def position_to_index(
    text: str,
    *,
    line: int,
    character: int,
    position_encoding: PositionEncodingKind | str | None = None,
) -> int:
    if line < 0 or character < 0:
        raise InvalidTextLocationError("Text positions must be non-negative")

    lines = text.splitlines(keepends=True)
    if not lines:
        if line == 0 and character == 0:
            return 0
        raise InvalidTextLocationError("Text position is outside the file")

    if line > len(lines):
        raise InvalidTextLocationError("Text line is outside the file")

    if line == len(lines):
        if character != 0:
            raise InvalidTextLocationError("Text character is outside the file")
        return len(text)

    raw_line = lines[line]
    logical_line = raw_line.rstrip("\r\n")
    character_index = _code_units_to_index(
        logical_line,
        character,
        normalize_position_encoding(position_encoding),
    )
    return sum(len(lines[idx]) for idx in range(line)) + character_index


def index_to_position(
    text: str,
    index: int,
    *,
    position_encoding: PositionEncodingKind | str | None = None,
) -> tuple[int, int]:
    if index < 0 or index > len(text):
        raise InvalidTextLocationError("Text index is outside the file")

    lines = text.splitlines(keepends=True)
    if not lines:
        return 0, 0

    if index == len(text) and text.endswith(("\r\n", "\n", "\r")):
        return len(lines), 0

    offset = 0
    encoding = normalize_position_encoding(position_encoding)
    for line_number, raw_line in enumerate(lines):
        next_offset = offset + len(raw_line)
        if index <= next_offset:
            logical_line = raw_line.rstrip("\r\n")
            character_index = min(index - offset, len(logical_line))
            character = count_position_units(
                logical_line[:character_index], encoding
            )
            return line_number, character
        offset = next_offset

    return len(lines), 0


def normalize_newlines(text: str, newline: str) -> str:
    return _NEWLINE_PATTERN.sub(newline, text)


@dataclass(slots=True)
class LoadedTextDocument:
    path: Path
    text: str
    encoding: str
    newline: str
    position_encoding: PositionEncodingKind = PositionEncodingKind.UTF16

    @classmethod
    def read(
        cls,
        path: Path,
        *,
        position_encoding: PositionEncodingKind | str | None = None,
    ) -> LoadedTextDocument:
        raw = path.read_bytes()
        encoding = _detect_encoding(raw)
        text = raw.decode(encoding)
        return cls(
            path=path,
            text=text,
            encoding=encoding,
            newline=_detect_newline(text),
            position_encoding=normalize_position_encoding(position_encoding),
        )

    def normalize_newlines(self, text: str) -> str:
        return normalize_newlines(text, self.newline)

    def position_to_index(self, *, line: int, character: int) -> int:
        return position_to_index(
            self.text,
            line=line,
            character=character,
            position_encoding=self.position_encoding,
        )

    def index_to_position(self, index: int) -> tuple[int, int]:
        return index_to_position(
            self.text,
            index,
            position_encoding=self.position_encoding,
        )

    def apply_edit(
        self,
        *,
        start_line: int,
        start_character: int,
        end_line: int,
        end_character: int,
        new_text: str,
    ) -> str:
        normalized = self.normalize_newlines(new_text)
        start_index = self.position_to_index(
            line=start_line, character=start_character
        )
        end_index = self.position_to_index(line=end_line, character=end_character)
        if end_index < start_index:
            raise InvalidTextLocationError("Invalid edit range: end is before start")
        return f"{self.text[:start_index]}{normalized}{self.text[end_index:]}"

    def write(self, updated_text: str) -> None:
        self.path.write_bytes(updated_text.encode(self.encoding))


def _code_units_to_index(
    text: str, target_units: int, position_encoding: PositionEncodingKind
) -> int:
    if target_units < 0:
        raise InvalidTextLocationError("Text character is outside the target line")

    if position_encoding is PositionEncodingKind.UTF32:
        if target_units > len(text):
            raise InvalidTextLocationError("Text character is outside the target line")
        return target_units

    consumed_units = 0
    for index, char in enumerate(text):
        if consumed_units == target_units:
            return index

        consumed_units += count_position_units(char, position_encoding)
        if consumed_units > target_units:
            raise InvalidTextLocationError(
                "Text character splits a multi-unit character"
            )

    if consumed_units == target_units:
        return len(text)

    raise InvalidTextLocationError("Text character is outside the target line")


def _detect_encoding(raw: bytes) -> str:
    for bom, encoding in _UTF_BOM_ENCODINGS:
        if raw.startswith(bom):
            return encoding

    if not raw:
        return "utf-8"

    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        if best_match := charset_normalizer.from_bytes(raw).best():
            if best_match.encoding:
                return best_match.encoding
        raise
    return "utf-8"


def _detect_newline(text: str) -> str:
    counts = {
        "\r\n": text.count("\r\n"),
        "\n": text.count("\n") - text.count("\r\n"),
        "\r": text.count("\r") - text.count("\r\n"),
    }
    if not any(counts.values()):
        return "\n"
    return max(counts, key=counts.__getitem__)
