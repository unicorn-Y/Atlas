# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/apply-patch/src/parser.rs (Apache-2.0)
# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/apply-patch/src/streaming_parser.rs (Apache-2.0)
# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/apply-patch/src/file_update.rs (Apache-2.0)
# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/apply-patch/src/seek_sequence.rs (Apache-2.0)
# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/apply-patch/src/text_file.rs (Apache-2.0)
# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276ede: apps/zcode-cli/packages/core/src/tool/edit-matchers.ts (Apache-2.0)
# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276ede: apps/zcode-cli/packages/core/src/tool/read-file-state.ts (Apache-2.0)
# SPDX-License-Identifier: Apache-2.0
"""Three edit tools behind the existing orchestrator's approval/checkpoint gate.

Read snapshots belong to this session's manager, not to a second database. Existing
read tools call note_read with the actual returned full content; read_file is an
optional atomic read/snapshot helper. Unknown text encodings are rejected rather
than decoded lossily. Atomic replacement is per file; a multi-file patch reports
any committed changes if a later OS operation fails.
"""
from __future__ import annotations

import asyncio
import codecs
import difflib
import hashlib
import os
import re
import stat
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required,
                           "additionalProperties": False}}}


EDIT_TOOLS = [
    _schema("apply_patch", "Apply a Codex *** Begin Patch patch with Add/Delete/Update File and optional Move to. Existing files must have been read and remain unchanged.",
            {"patch": {"type": "string"}}, ["patch"]),
    _schema("edit", "Replace old_string in a file already fully read. Exact match is preferred; fallback matches must be unique. Stale files require a new read.",
            {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"},
             "replace_all": {"type": "boolean", "default": False}}, ["path", "old_string", "new_string"]),
    _schema("write", "Write full text. Existing files must first be fully read. Preserves their BOM, encoding and newline style; new files use UTF-8.",
            {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
]
EDIT_TOOL_NAMES = frozenset(item["function"]["name"] for item in EDIT_TOOLS)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _decode(raw: bytes, encoding: str | None) -> tuple[str, str, bytes]:
    for bom, codec in ((codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
                       (codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"),
                       (codecs.BOM_UTF16_BE, "utf-16-be")):
        if raw.startswith(bom):
            return raw[len(bom):].decode(codec), codec, bom
    codec = encoding or "utf-8"
    if codecs.lookup(codec).name == "utf-8-sig":
        codec = "utf-8"
    # Explicit encoding is supplied by the existing read route for legacy files.
    text = raw.decode(codec, errors="strict")
    if "\x00" in text:
        raise ValueError("Binary or BOM-less UTF-16 file: supply its text encoding when reading")
    return text, codec, b""


def _newline(text: str) -> str:
    match = re.search(r"\r\n|\r|\n", text)
    return match.group() if match else "\n"


def _normalize(text: str) -> str:
    return re.sub(r"\r\n|\r", "\n", text)


def _normal_map(text: str) -> tuple[str, list[int]]:
    chars, positions = [], []
    index = 0
    while index < len(text):
        positions.append(index)
        if text.startswith("\r\n", index):
            chars.append("\n")
            index += 2
        else:
            chars.append("\n" if text[index] == "\r" else text[index])
            index += 1
    positions.append(len(text))
    return "".join(chars), positions


def _lines(text: str) -> list[tuple[str, str]]:
    return [(m[1], m[2]) for m in re.finditer(r"([^\r\n]*)(\r\n|\r|\n|$)", text) if m[0]]


def _preserve_newlines(text: str, original: str, preferred: str) -> str:
    """Keep unchanged lines' individual endings, including mixed CRLF/LF files."""
    old, new = _lines(original), _lines(text)
    endings = [preferred if ending else "" for _, ending in new]
    matcher = difflib.SequenceMatcher(a=[line for line, _ in old], b=[line for line, _ in new], autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            ending = old[block.a + offset][1]
            if ending and new[block.b + offset][1]:
                endings[block.b + offset] = ending
    return "".join(line + ending for (line, _), ending in zip(new, endings))


def _diff(before: str, after: str, source: str, target: str) -> str:
    lines = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                 fromfile=source, tofile=target)
    return "".join(line if line.endswith(("\n", "\r")) else line + "\n\\ No newline at end of file\n" for line in lines)


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_PUNCTUATION = str.maketrans({**{c: "-" for c in "‐‑‒–—―−"},
                            **{c: "'" for c in "‘’‚‛"}, **{c: '"' for c in "“”„‟"},
                            **{c: " " for c in "\u00a0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000"}})


def _visible(text: str) -> str:
    values = {"n": "\n", "t": "\t", "r": "\r"}
    return re.sub(r'''\\([ntr"'`\\$])''', lambda m: values.get(m[1], m[1]), text)


def _unicode(text: str) -> str:
    return re.sub(r"(\\\\)|\\u([0-9a-fA-F]{4})", lambda m: m[0] if m[1] else chr(int(m[2], 16)), text)


def _positions(content: str, search: str) -> list[tuple[int, int]]:
    if not search:
        return []
    return [(m.start(), m.end()) for m in re.finditer(re.escape(search), content)]


def _dedent(lines: list[str]) -> str:
    nonempty = [line for line in lines if line.strip()]
    indent = min((len(line) - len(line.lstrip(" \t")) for line in nonempty), default=0)
    return "\n".join(line[indent:] if line.strip() else line for line in lines)


def _similarity(left: str, right: str) -> float:
    # ZCode's Levenshtein similarity, not SequenceMatcher's different score.
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        row = [i]
        for j, b in enumerate(right, 1):
            row.append(min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = row
    return 1 - previous[-1] / max(len(left), len(right), 1)


def find_edit_match(content: str, search: str, replace_all: bool = False) -> tuple[str, list[tuple[int, int]]]:
    """ZCode strategy ordering, strengthened to require a unique location."""
    if not search:
        raise ValueError("old_string must not be empty; use write to create content")
    strategies: list[tuple[str, list[tuple[int, int]]]] = [
        ("exact", _positions(content, search)),
        ("quote_normalized", _positions(content.translate(_QUOTES), search.translate(_QUOTES))),
    ]
    numbered = [re.match(r"^\d+(?:: |\t)(.*)$", line) for line in search.split("\n")]
    if all(numbered):
        strategies.append(("line_number_prefix_stripped", _positions(content, "\n".join(m[1] for m in numbered if m))))
    strategies.extend([("escape_normalized", _positions(content, _visible(search))),
                       ("unicode_escape_normalized", _positions(content, _unicode(search)))])
    for strategy, candidates in strategies:
        if candidates:
            if len(candidates) != 1 and not replace_all:
                raise ValueError(f"Ambiguous {strategy} edit: {len(candidates)} matches; provide more context")
            return strategy, candidates
    if replace_all:
        raise ValueError("replace_all requires an exact or narrow normalized match")
    lines = content.split("\n")
    search_lines = search.split("\n")
    if search_lines[-1] == "":
        search_lines.pop()
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    for strategy in ("line_trimmed", "indentation_flexible", "block_anchor"):
        candidates = []
        for i in range(len(lines) - len(search_lines) + 1):
            block = lines[i:i + len(search_lines)]
            if strategy == "line_trimmed":
                matches = all(a.strip() == b.strip() for a, b in zip(block, search_lines))
            elif strategy == "indentation_flexible":
                matches = len(block) >= 2 and _dedent(block) == _dedent(search_lines)
            else:
                matches = (len(block) >= 3 and block[0].strip() == search_lines[0].strip()
                           and block[-1].strip() == search_lines[-1].strip()
                           and sum(_similarity(a.strip(), b.strip()) for a, b in zip(block[1:-1], search_lines[1:-1])) / (len(block) - 2) >= 0.8)
            if matches:
                end = offsets[i] + len("\n".join(block))
                if search.endswith("\n") and end < len(content) and content[end] == "\n":
                    end += 1
                candidates.append((offsets[i], end))
        if candidates:
            if len(candidates) != 1:
                raise ValueError(f"Ambiguous {strategy} edit: {len(candidates)} matches; provide more context")
            return strategy, candidates
    raise ValueError("old_string was not found; read the current file and provide exact context")


def _quote_style(actual: str, replacement: str) -> str:
    for straight, opening, closing in (("'", "‘", "’"), ('"', "“", "”")):
        if opening not in actual and closing not in actual:
            continue
        chars = list(replacement)
        for i, char in enumerate(chars):
            if char == straight:
                apostrophe = (straight == "'" and i > 0 and i + 1 < len(chars)
                              and chars[i - 1].isalpha() and chars[i + 1].isalpha())
                chars[i] = closing if apostrophe else opening if i == 0 or chars[i - 1] in " \t\r\n([{—–" else closing
        replacement = "".join(chars)
    return replacement


@dataclass
class PatchChunk:
    context: str | None = None
    old: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    context_indices: list[tuple[int, int]] = field(default_factory=list)
    eof: bool = False


@dataclass
class PatchHunk:
    kind: str
    path: str
    move_to: str | None = None
    content: str = ""
    chunks: list[PatchChunk] = field(default_factory=list)


def parse_patch(patch: str) -> list[PatchHunk]:
    lines = _normalize(patch.strip()).split("\n")
    if lines and lines[0] in {"<<EOF", "<<'EOF'", '<<"EOF"'} and lines[-1].endswith("EOF"):
        lines = lines[1:-1]
    if len(lines) < 2 or lines[0].strip() != "*** Begin Patch" or lines[-1].strip() != "*** End Patch":
        raise ValueError("Patch must start with *** Begin Patch and end with *** End Patch")
    hunks: list[PatchHunk] = []
    current: PatchHunk | None = None

    def finish() -> None:
        if current and current.kind == "update" and (not current.chunks or any(not c.old and not c.new for c in current.chunks)):
            raise ValueError(f"Empty update hunk: {current.path}")

    for number, line in enumerate(lines[1:-1], 2):
        header = re.fullmatch(r"\*\*\* (Add|Delete|Update) File: (.+)", line.strip())
        if header:
            finish()
            current = PatchHunk(header[1].lower(), header[2])
            hunks.append(current)
            continue
        if current is None:
            if line.strip().startswith("*** Environment ID:"):
                raise ValueError("Environment-qualified patches must be routed to that environment, not the local editor")
            raise ValueError(f"Invalid patch hunk header at line {number}")
        if current.kind == "add" and line.startswith("+"):
            current.content += line[1:] + "\n"
            continue
        if current.kind != "update":
            raise ValueError(f"Invalid {current.kind} patch line {number}")
        marker = line.rstrip()
        if marker.startswith("*** Move to: ") and not current.chunks and current.move_to is None:
            current.move_to = marker[len("*** Move to: "):].strip()
            if not current.move_to:
                raise ValueError("Move destination must not be empty")
            continue
        if marker == "@@" or marker.startswith("@@ "):
            if current.chunks and not current.chunks[-1].old and not current.chunks[-1].new:
                raise ValueError(f"Empty update chunk at line {number}")
            current.chunks.append(PatchChunk(context=marker[3:] if marker.startswith("@@ ") else None))
            continue
        if marker == "*** End of File":
            if not current.chunks or not (current.chunks[-1].old or current.chunks[-1].new):
                raise ValueError(f"Empty EOF chunk at line {number}")
            current.chunks[-1].eof = True
            continue
        if current.chunks and current.chunks[-1].eof:
            if not line.strip():
                continue
            raise ValueError(f"Expected @@ after EOF at line {number}")
        if not line or line[0] in " +-":
            if not current.chunks:
                current.chunks.append(PatchChunk())
            chunk = current.chunks[-1]
            prefix, text = (line[0], line[1:]) if line else (" ", "")
            if prefix == " ":
                chunk.context_indices.append((len(chunk.old), len(chunk.new)))
            if prefix in " -":
                chunk.old.append(text)
            if prefix in " +":
                chunk.new.append(text)
            continue
        raise ValueError(f"Invalid update line {number}: expected space, + or -")
    finish()
    if not hunks:
        raise ValueError("No files were modified")
    return hunks


def _seek(lines: list[str], pattern: list[str], start: int, eof: bool = False) -> int | None:
    if not pattern:
        return start
    begin = max(start, len(lines) - len(pattern)) if eof else start
    for normalize in (lambda s: s, str.rstrip, str.strip, lambda s: s.strip().translate(_PUNCTUATION)):
        candidates = [i for i in range(begin, len(lines) - len(pattern) + 1)
                      if all(normalize(a) == normalize(b) for a, b in zip(lines[i:i + len(pattern)], pattern))]
        if len(candidates) > 1:
            raise ValueError("Ambiguous patch context; supply a more specific @@ anchor or larger context")
        if candidates:
            return candidates[0]
    return None


def apply_chunks(text: str, chunks: list[PatchChunk]) -> str:
    records = _lines(text)
    original = [line for line, _ in records]
    ending = _newline(text)
    replacements: list[tuple[int, int, list[str]]] = []
    cursor = 0
    for chunk in chunks:
        if chunk.context is not None:
            anchor = _seek(original, [chunk.context], cursor)
            if anchor is None:
                raise ValueError(f"Patch context not found: {chunk.context}")
            cursor = anchor + 1
        if not chunk.old:
            replacements.append((len(original), 0, chunk.new))
            continue
        old, new = chunk.old, chunk.new
        index = _seek(original, old, cursor, chunk.eof)
        if index is None and old[-1] == "":
            old = old[:-1]
            new = new[:-1] if new and new[-1] == "" else new
            index = _seek(original, old, cursor, chunk.eof)
        if index is None:
            raise ValueError("Patch expected lines not found; re-read the file")
        old_start = new_start = 0
        for old_context, new_context in chunk.context_indices:
            if old_context >= len(old) or new_context >= len(new):
                break
            if old_start != old_context or new_start != new_context:
                replacements.append((index + old_start, old_context - old_start, new[new_start:new_context]))
            old_start, new_start = old_context + 1, new_context + 1
        if old_start != len(old) or new_start != len(new):
            replacements.append((index + old_start, len(old) - old_start, new[new_start:]))
        cursor = index + len(old)
    rebuilt: list[tuple[str, str]] = []
    cursor = 0
    for start, count, replacement in sorted(replacements, key=lambda r: r[0]):
        if start < cursor:
            raise ValueError("Overlapping patch chunks")
        rebuilt.extend(records[cursor:start])
        rebuilt.extend((line, ending) for line in replacement)
        cursor = start + count
    rebuilt.extend(records[cursor:])
    # Atlas preserves an existing missing final newline instead of adding one.
    if rebuilt and records and not records[-1][1]:
        rebuilt[-1] = (rebuilt[-1][0], "")
    return "".join(line + (terminator or ending if i < len(rebuilt) - 1 else terminator)
                   for i, (line, terminator) in enumerate(rebuilt))


@dataclass(frozen=True)
class ReadSnapshot:
    raw: bytes
    text: str
    encoding: str
    bom: bytes
    mtime_ns: int
    mode: int
    complete: bool = True


class EditManager:
    def __init__(self, workspace: str | Path, *, allowed_paths: list[str] | None = None,
                 encoding: str | None = None) -> None:
        self.workspace = Path(workspace).resolve()
        self.allowed_paths = [Path(p).resolve() for p in allowed_paths] if allowed_paths is not None else None
        self.encoding = encoding
        self.reads: dict[str, ReadSnapshot] = {}
        self._lock = threading.RLock()

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        import copy
        return copy.deepcopy(EDIT_TOOLS)

    def register_tools(self, register: Callable[..., Any]) -> list[str]:
        for item in self.get_tools_for_llm():
            function = item["function"]
            name = function["name"]
            register(name=name, toolset="atlas", schema=function,
                     description=function["description"], is_async=False,
                     handler=lambda args, _name=name, **_kwargs: self.call_tool(_name, args))
        return [item["function"]["name"] for item in EDIT_TOOLS]

    def _path(self, raw: str | Path) -> Path:
        if not str(raw).strip():
            raise ValueError("File path must not be empty")
        path = Path(raw).expanduser()
        path = (path if path.is_absolute() else self.workspace / path).resolve()
        if self.allowed_paths is not None and not any(path == root or root in path.parents for root in self.allowed_paths):
            raise PermissionError(f"File is outside the authorized paths: {path}")
        return path

    def target_paths(self, name: str, arguments: dict[str, Any]) -> list[str]:
        """Resolve every write target without changing files, for safety/checkpoints."""
        if name in {"edit", "write"}:
            paths = [self._path(arguments["path"])]
        elif name == "apply_patch":
            paths = []
            for hunk in parse_patch(str(arguments.get("patch") or arguments.get("input") or "")):
                paths.append(self._path(hunk.path))
                if hunk.move_to:
                    paths.append(self._path(hunk.move_to))
        else:
            raise ValueError(f"Unknown edit tool: {name}")
        return list(dict.fromkeys(str(path) for path in paths))

    @staticmethod
    def _key(path: Path) -> str:
        return os.path.normcase(str(path))

    def _snapshot(self, path: Path, encoding: str | None = None, complete: bool = True) -> ReadSnapshot:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            raw = stream.read()
            after = os.fstat(stream.fileno())
        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise ValueError("File changed during read; read it again")
        text, codec, bom = _decode(raw, encoding or self.encoding)
        return ReadSnapshot(raw, text, codec, bom, after.st_mtime_ns, stat.S_IMODE(after.st_mode), complete)

    def read_file(self, path: str | Path, *, encoding: str | None = None) -> str:
        with self._lock:
            resolved = self._path(path)
            snapshot = self._snapshot(resolved, encoding)
            self.reads[self._key(resolved)] = snapshot
            return snapshot.text

    def note_read(self, path: str | Path, content: str | bytes | None = None, *,
                  encoding: str | None = None, complete: bool = True) -> None:
        with self._lock:
            resolved = self._path(path)
            snapshot = self._snapshot(resolved, encoding, complete)
            if content is not None and complete:
                actual = snapshot.raw if isinstance(content, bytes) else snapshot.text
                observed = content
                if isinstance(observed, str) and snapshot.bom and observed.startswith("\ufeff"):
                    observed = observed[1:]
                if actual != observed:
                    raise ValueError("Read content no longer matches the file; read it again")
            self.reads[self._key(resolved)] = snapshot

    def _existing(self, path: Path) -> ReadSnapshot:
        snapshot = self.reads.get(self._key(path))
        if snapshot is None or not snapshot.complete:
            raise ValueError(f"READ_REQUIRED: fully read {path} before modifying it")
        self._check(path, snapshot)
        return snapshot

    @staticmethod
    def _check(path: Path, snapshot: ReadSnapshot | None) -> None:
        if snapshot is None:
            if path.exists():
                raise ValueError(f"STALE_FILE: file was created meanwhile; read {path}")
            return
        if not path.is_file() or path.stat().st_mtime_ns != snapshot.mtime_ns or path.read_bytes() != snapshot.raw:
            raise ValueError(f"STALE_FILE: content changed since read; read {path} again")

    def _atomic_write(self, path: Path, raw: bytes, previous: ReadSnapshot | None) -> None:
        self._check(path, previous)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if previous:
                os.chmod(temporary, previous.mode)
            self._check(path, previous)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self.call_tool, name, arguments)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            changes: list[dict[str, Any]] = []
            mutation_started = False
            try:
                operations: list[tuple[Path, str | None, ReadSnapshot | None, str]] = []
                if name in {"edit", "write"}:
                    path = self._path(arguments["path"])
                    previous = self._existing(path) if path.exists() else None
                    if name == "edit":
                        if previous is None:
                            raise ValueError("edit requires an existing, previously read file")
                        content, positions = _normal_map(previous.text)
                        old = _normalize(str(arguments["old_string"]))
                        replacement = _normalize(str(arguments["new_string"]))
                        strategy, matches = find_edit_match(content, old, bool(arguments.get("replace_all", False)))
                        if strategy == "escape_normalized":
                            replacement = _normalize(_visible(replacement))
                        text = previous.text
                        for start, end in reversed(matches):
                            new = _quote_style(content[start:end], replacement) if strategy == "quote_normalized" else replacement
                            new = _preserve_newlines(new, text[positions[start]:positions[end]], _newline(previous.text))
                            text = text[:positions[start]] + new + text[positions[end]:]
                    else:
                        strategy = "write"
                        text = _normalize(str(arguments["content"]))
                        if previous:
                            text = _preserve_newlines(text, previous.text, _newline(previous.text))
                    operations.append((path, text, previous, strategy))
                elif name == "apply_patch":
                    for hunk in parse_patch(str(arguments.get("patch") or arguments.get("input") or "")):
                        path = self._path(hunk.path)
                        previous = self._existing(path) if path.exists() else None
                        if hunk.kind in {"update", "delete"} and previous is None:
                            raise ValueError(f"Patch requires an existing, read file: {path}")
                        if hunk.kind == "add":
                            text = _preserve_newlines(hunk.content, previous.text, _newline(previous.text)) if previous else hunk.content
                            operations.append((path, text, previous, "add"))
                        elif hunk.kind == "delete":
                            operations.append((path, None, previous, "delete"))
                        else:
                            assert previous is not None
                            text = apply_chunks(previous.text, hunk.chunks)
                            if hunk.move_to:
                                destination = self._path(hunk.move_to)
                                if destination == path:
                                    raise ValueError("Move destination equals the source")
                                if destination.exists():
                                    raise ValueError("Move destination exists; choose a new destination")
                                # Rename retains the source codec/BOM via explicit staged bytes below.
                                operations.append((destination, text, None, f"move:{path}"))
                                operations.append((path, None, previous, "delete"))
                            else:
                                operations.append((path, text, previous, "update"))
                else:
                    raise ValueError(f"Unknown edit tool: {name}")
                keys = [self._key(path) for path, _, _, _ in operations]
                if len(keys) != len(set(keys)):
                    raise ValueError("Patch touches a path more than once; combine its chunks")
                # Validate and encode every file before the first mutation.
                prepared = []
                for path, text, previous, strategy in operations:
                    self._check(path, previous)
                    codec_source = self.reads[self._key(Path(strategy[5:]))] if strategy.startswith("move:") else previous
                    codec = codec_source.encoding if codec_source else "utf-8"
                    bom = codec_source.bom if codec_source else b""
                    raw = None if text is None else bom + text.encode(codec, errors="strict")
                    before_text = previous.text if previous else ""
                    diff = _diff(before_text, text or "", str(path) if previous else "/dev/null",
                                 str(path) if text is not None else "/dev/null")
                    prepared.append((path, text, raw, previous, strategy, diff, codec))
                for path, text, raw, previous, strategy, diff, codec in prepared:
                    self._check(path, previous)
                    mutation_started = True
                    if raw is None:
                        path.unlink()
                        self.reads.pop(self._key(path), None)
                    else:
                        self._atomic_write(path, raw, previous)
                        self.reads[self._key(path)] = self._snapshot(path, codec)
                    changes.append({"path": str(path), "strategy": strategy, "diff": diff,
                                    "before_hash": _digest(previous.raw) if previous else None,
                                    "after_hash": _digest(raw) if raw is not None else None,
                                    "encoding": codec})
                data = {"changes": changes, "changed_paths": [c["path"] for c in changes],
                        "diff": "\n".join(c["diff"] for c in changes), "outcome": "completed"}
                return {"data": data, "content": [{"type": "text", "text": data["diff"] or "No text changes."}],
                        "is_error": False, "outcome": "completed"}
            except Exception as exc:
                outcome = "unknown" if mutation_started else "not_started"
                data = {"error": f"{type(exc).__name__}: {exc}", "changes": changes,
                        "changed_paths": [c["path"] for c in changes], "outcome": outcome}
                return {"data": data, "content": [{"type": "text", "text": data["error"]}],
                        "is_error": True, "outcome": outcome}
