from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Protocol

_MIN_PATCH_LINES = 2


class DiffError(ValueError):
    pass


class ActionType(StrEnum):
    ADD = auto()
    DELETE = auto()
    UPDATE = auto()


@dataclass(slots=True)
class FileChange:
    type: ActionType
    old_content: str | None = None
    new_content: str | None = None
    move_path: str | None = None


@dataclass(slots=True)
class Commit:
    changes: dict[str, FileChange] = field(default_factory=dict)


@dataclass(slots=True)
class Chunk:
    orig_index: int = -1
    del_lines: list[str] = field(default_factory=list)
    ins_lines: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PatchAction:
    type: ActionType
    new_file: str | None = None
    chunks: list[Chunk] = field(default_factory=list)
    move_path: str | None = None


@dataclass(slots=True)
class Patch:
    actions: dict[str, PatchAction] = field(default_factory=dict)


class OpenFileFn(Protocol):
    def __call__(self, path: str) -> str: ...


class WriteFileFn(Protocol):
    def __call__(self, path: str, content: str) -> None: ...


class RemoveFileFn(Protocol):
    def __call__(self, path: str) -> None: ...


@dataclass(slots=True)
class Parser:
    current_files: dict[str, str]
    lines: list[str]
    index: int = 0
    patch: Patch = field(default_factory=Patch)
    fuzz: int = 0

    def is_done(self, prefixes: tuple[str, ...] | None = None) -> bool:
        if self.index >= len(self.lines):
            return True
        return bool(prefixes and self.lines[self.index].startswith(prefixes))

    def startswith(self, prefix: str | tuple[str, ...]) -> bool:
        if self.index >= len(self.lines):
            return False
        return self.lines[self.index].startswith(prefix)

    def read_str(self, prefix: str = "", *, return_everything: bool = False) -> str:
        if self.index >= len(self.lines):
            return ""
        line = self.lines[self.index]
        if not line.startswith(prefix):
            return ""
        self.index += 1
        return line if return_everything else line[len(prefix) :]

    def parse(self) -> None:
        while not self.is_done(("*** End Patch",)):
            if self.index < len(self.lines) and not self.lines[self.index].strip():
                self.index += 1
                continue

            if path := self.read_str("*** Update File: "):
                if path in self.patch.actions:
                    raise DiffError(f"Update File Error: Duplicate Path: {path}")
                if path not in self.current_files:
                    raise DiffError(f"Update File Error: Missing File: {path}")
                move_to = self.read_str("*** Move to: ") or None
                action = self.parse_update_file(self.current_files[path])
                action.move_path = move_to
                self.patch.actions[path] = action
                continue

            if path := self.read_str("*** Delete File: "):
                if path in self.patch.actions:
                    raise DiffError(f"Delete File Error: Duplicate Path: {path}")
                if path not in self.current_files:
                    raise DiffError(f"Delete File Error: Missing File: {path}")
                self.patch.actions[path] = PatchAction(type=ActionType.DELETE)
                continue

            if path := self.read_str("*** Add File: "):
                if path in self.patch.actions:
                    raise DiffError(f"Add File Error: Duplicate Path: {path}")
                self.patch.actions[path] = self.parse_add_file()
                continue

            raise DiffError(f"Unknown Line: {self.lines[self.index]}")

        if not self.startswith("*** End Patch"):
            raise DiffError("Missing End Patch")
        self.index += 1

    def parse_update_file(self, text: str) -> PatchAction:
        action = PatchAction(type=ActionType.UPDATE)
        lines = text.split("\n")
        index = 0

        while not self.is_done((
            "*** End Patch",
            "*** Update File:",
            "*** Delete File:",
            "*** Add File:",
            "*** End of File",
        )):
            def_str = self.read_str("@@ ")
            has_section = False
            if (
                not def_str
                and self.index < len(self.lines)
                and self.lines[self.index] == "@@"
            ):
                has_section = True
                self.index += 1

            if not (def_str or has_section or index == 0):
                raise DiffError(f"Invalid Line:\n{self.lines[self.index]}")

            if def_str.strip():
                index = self._advance_to_context(lines, index, def_str)

            context, chunks, end_index, eof = peek_next_section(self.lines, self.index)
            new_index, fuzz = find_context(lines, context, index, eof)
            if new_index == -1:
                next_chunk_text = "\n".join(context)
                if eof:
                    raise DiffError(f"Invalid EOF Context {index}:\n{next_chunk_text}")
                raise DiffError(f"Invalid Context {index}:\n{next_chunk_text}")

            self.fuzz += fuzz
            for chunk in chunks:
                chunk.orig_index += new_index
                action.chunks.append(chunk)
            index = new_index + len(context)
            self.index = end_index

        return action

    def _advance_to_context(self, lines: list[str], index: int, def_str: str) -> int:
        for current_index, line in enumerate(lines[index:], start=index):
            if line == def_str:
                return current_index + 1

        stripped_target = def_str.strip()
        for current_index, line in enumerate(lines[index:], start=index):
            if line.strip() == stripped_target:
                self.fuzz += 1
                return current_index + 1

        return index

    def parse_add_file(self) -> PatchAction:
        lines: list[str] = []
        while not self.is_done((
            "*** End Patch",
            "*** Update File:",
            "*** Delete File:",
            "*** Add File:",
        )):
            value = self.read_str(return_everything=True)
            if not value.strip():
                continue
            if not value.startswith("+"):
                raise DiffError(f"Invalid Add File Line: {value}")
            lines.append(value[1:])

        return PatchAction(type=ActionType.ADD, new_file="\n".join(lines))


def find_context_core(
    lines: list[str], context: list[str], start: int
) -> tuple[int, int]:
    if not context:
        return start, 0

    for index in range(start, len(lines)):
        if lines[index : index + len(context)] == context:
            return index, 0

    stripped_context = [line.rstrip() for line in context]
    for index in range(start, len(lines)):
        if [
            line.rstrip() for line in lines[index : index + len(context)]
        ] == stripped_context:
            return index, 1

    fully_stripped_context = [line.strip() for line in context]
    for index in range(start, len(lines)):
        if [
            line.strip() for line in lines[index : index + len(context)]
        ] == fully_stripped_context:
            return index, 100

    return -1, 0


def find_context(
    lines: list[str], context: list[str], start: int, eof: bool
) -> tuple[int, int]:
    if not eof:
        return find_context_core(lines, context, start)

    new_index, fuzz = find_context_core(lines, context, len(lines) - len(context))
    if new_index != -1:
        return new_index, fuzz

    new_index, fuzz = find_context_core(lines, context, start)
    return new_index, fuzz + 10_000


def peek_next_section(
    lines: list[str], index: int
) -> tuple[list[str], list[Chunk], int, bool]:
    old: list[str] = []
    del_lines: list[str] = []
    ins_lines: list[str] = []
    chunks: list[Chunk] = []
    mode = "keep"
    start_index = index

    while index < len(lines):
        line = lines[index]
        if line.startswith((
            "@@",
            "*** End Patch",
            "*** Update File:",
            "*** Delete File:",
            "*** Add File:",
            "*** End of File",
        )):
            break
        if line == "***":
            break
        if line.startswith("***"):
            raise DiffError(f"Invalid Line: {line}")

        index += 1
        previous_mode = mode
        normalized = " " if line == "" else line
        match normalized[0]:
            case "+":
                mode = "add"
            case "-":
                mode = "delete"
            case " ":
                mode = "keep"
            case _:
                raise DiffError(f"Invalid Line: {line}")

        payload = normalized[1:]
        if mode == "keep" and previous_mode != mode and (ins_lines or del_lines):
            chunks.append(
                Chunk(
                    orig_index=len(old) - len(del_lines),
                    del_lines=del_lines,
                    ins_lines=ins_lines,
                )
            )
            del_lines = []
            ins_lines = []

        match mode:
            case "delete":
                del_lines.append(payload)
                old.append(payload)
            case "add":
                ins_lines.append(payload)
            case "keep":
                old.append(payload)

    if ins_lines or del_lines:
        chunks.append(
            Chunk(
                orig_index=len(old) - len(del_lines),
                del_lines=del_lines,
                ins_lines=ins_lines,
            )
        )

    if index < len(lines) and lines[index] == "*** End of File":
        return old, chunks, index + 1, True
    if index == start_index:
        raise DiffError(f"Nothing in this section - index={index} line={lines[index]}")
    return old, chunks, index, False


def identify_files_needed(text: str) -> list[str]:
    paths: set[str] = set()
    for line in text.strip().split("\n"):
        if line.startswith("*** Update File: "):
            paths.add(line.removeprefix("*** Update File: "))
        if line.startswith("*** Delete File: "):
            paths.add(line.removeprefix("*** Delete File: "))
    return sorted(paths)


def identify_changed_files(text: str) -> list[str]:
    paths: list[str] = []
    current_update_path: str | None = None

    for raw_line in text.strip().split("\n"):
        if raw_line.startswith("*** Add File: "):
            paths.append(raw_line.removeprefix("*** Add File: "))
            current_update_path = None
            continue
        if raw_line.startswith("*** Delete File: "):
            paths.append(raw_line.removeprefix("*** Delete File: "))
            current_update_path = None
            continue
        if raw_line.startswith("*** Update File: "):
            current_update_path = raw_line.removeprefix("*** Update File: ")
            paths.append(current_update_path)
            continue
        if raw_line.startswith("*** Move to: ") and current_update_path is not None:
            paths.append(raw_line.removeprefix("*** Move to: "))

    return paths


def text_to_patch(text: str, original_files: dict[str, str]) -> tuple[Patch, int]:
    lines = text.strip().split("\n")
    if (
        len(lines) < _MIN_PATCH_LINES
        or not lines[0].startswith("*** Begin Patch")
        or lines[-1] != "*** End Patch"
    ):
        raise DiffError("Invalid patch text")

    parser = Parser(current_files=original_files, lines=lines, index=1)
    parser.parse()
    return parser.patch, parser.fuzz


def _get_updated_file(text: str, action: PatchAction, path: str) -> str:
    if action.type != ActionType.UPDATE:
        raise DiffError(f"Expected update action for {path}")

    original_lines = text.split("\n")
    destination_lines: list[str] = []
    original_index = 0

    for chunk in action.chunks:
        if chunk.orig_index > len(original_lines):
            raise DiffError(
                f"{path}: chunk.orig_index {chunk.orig_index} exceeds file length {len(original_lines)}"
            )
        if original_index > chunk.orig_index:
            raise DiffError(
                f"{path}: original index {original_index} exceeds chunk index {chunk.orig_index}"
            )

        destination_lines.extend(original_lines[original_index : chunk.orig_index])
        original_index = chunk.orig_index
        destination_lines.extend(chunk.ins_lines)
        original_index += len(chunk.del_lines)

    destination_lines.extend(original_lines[original_index:])
    return "\n".join(destination_lines)


def patch_to_commit(patch: Patch, original_files: dict[str, str]) -> Commit:
    commit = Commit()
    for path, action in patch.actions.items():
        match action.type:
            case ActionType.DELETE:
                commit.changes[path] = FileChange(
                    type=ActionType.DELETE, old_content=original_files[path]
                )
            case ActionType.ADD:
                commit.changes[path] = FileChange(
                    type=ActionType.ADD, new_content=action.new_file
                )
            case ActionType.UPDATE:
                commit.changes[path] = FileChange(
                    type=ActionType.UPDATE,
                    old_content=original_files[path],
                    new_content=_get_updated_file(original_files[path], action, path),
                    move_path=action.move_path,
                )
    return commit


def load_files(paths: list[str], open_fn: OpenFileFn) -> dict[str, str]:
    return {path: open_fn(path) for path in paths}


def apply_commit(
    commit: Commit, write_fn: WriteFileFn, remove_fn: RemoveFileFn
) -> None:
    for path, change in commit.changes.items():
        match change.type:
            case ActionType.DELETE:
                remove_fn(path)
            case ActionType.ADD:
                write_fn(path, change.new_content or "")
            case ActionType.UPDATE:
                if change.move_path:
                    write_fn(change.move_path, change.new_content or "")
                    remove_fn(path)
                else:
                    write_fn(path, change.new_content or "")


def process_patch(
    text: str, open_fn: OpenFileFn, write_fn: WriteFileFn, remove_fn: RemoveFileFn
) -> tuple[Commit, int]:
    if not text.startswith("*** Begin Patch"):
        raise DiffError("Patch must start with '*** Begin Patch'")

    original_files = load_files(identify_files_needed(text), open_fn)
    patch, fuzz = text_to_patch(text, original_files)
    commit = patch_to_commit(patch, original_files)
    apply_commit(commit, write_fn, remove_fn)
    return commit, fuzz
