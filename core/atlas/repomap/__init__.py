# Ported from Aider-AI/aider@5dc9490bb35f9729ef2c95d00a19ccd30c26339c: aider/repomap.py (Apache-2.0)
"""Aider-derived tree-sitter repository map for Atlas workspaces."""

from __future__ import annotations

import fnmatch
import json
import math
import os
import re
import sqlite3
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .queries import TAG_QUERIES


REPOMAP_TOOL_SPEC: dict[str, Any] = {
    "name": "build_repo_map",
    "description": (
        "Summarize the most relevant symbol definitions and references in a repository. "
        "Use focus_files for files already in context (they boost references and are omitted "
        "from the map), mentioned for filenames or identifiers to boost, and max_tokens to "
        "bound the returned map."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "root": {"type": "string", "description": "Repository root directory."},
            "focus_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Repository files to prioritize in the map.",
            },
            "mentioned": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Mentioned file paths or symbol identifiers to prioritize.",
            },
            "max_tokens": {
                "type": "integer",
                "minimum": 1,
                "description": "Approximate maximum token budget for the map.",
            },
        },
        "required": ["root"],
        "additionalProperties": False,
    },
}

_UPDATING_MESSAGE = "Updating repo map"
_SKIP_DIRS = {".git", ".hg", ".svn"}
_TOKEN_PARTS = re.compile(r"[A-Za-z0-9_]+|[^\x00-\x7f]|[^\w\s]", re.UNICODE)


@dataclass(frozen=True)
class _Tag:
    rel_fname: str
    fname: str
    line: int
    name: str
    kind: str


@dataclass(frozen=True)
class _FileOnly:
    rel_fname: str
    fname: str


def build_repo_map(
    root: str,
    *,
    focus_files: list[str] = [],
    mentioned: list[str] = [],
    max_tokens: int = 2048,
) -> str:
    """Build a symbol map ranked by references, focus files, and mentions.

    Token accounting is an estimate because this interface has no model-specific tokenizer.
    Extracted tags are cached in ``<root>/data/repomap/tags.sqlite3`` by file mtime.
    """
    if max_tokens <= 0:
        return ""

    repo_root = Path(root).expanduser().resolve()
    if not repo_root.is_dir():
        return ""

    files = _source_files(repo_root)
    if not files:
        return ""

    try:
        from grep_ast import filename_to_lang
    except ImportError as exc:
        raise RuntimeError(
            "Repo maps require grep-ast, tree-sitter, and tree-sitter-language-pack."
        ) from exc

    source_files: list[tuple[str, Path, str]] = []
    for path in files:
        try:
            lang = filename_to_lang(str(path))
        except Exception:
            continue
        if not lang or lang not in TAG_QUERIES:
            continue
        rel = _relative_path(repo_root, path)
        source_files.append((rel, path, lang))

    if not source_files:
        return ""

    tags_by_file: dict[str, list[_Tag]] = {}
    connection = _open_tag_cache(repo_root)
    try:
        for rel_fname, path, lang in source_files:
            try:
                mtime_ns = path.stat().st_mtime_ns
            except OSError:
                continue
            tags_by_file[rel_fname] = _get_tags_cached(
                connection, repo_root, rel_fname, path, lang, mtime_ns
            )
        if connection is not None:
            connection.commit()
    finally:
        if connection is not None:
            connection.close()

    focus = _resolve_hints(repo_root, focus_files, [item[0] for item in source_files])
    mentions = _resolve_hints(repo_root, mentioned, [item[0] for item in source_files])
    mentioned_idents = {str(value) for value in mentioned if value}
    entries = _ranked_entries(tags_by_file, source_files, focus, mentions, mentioned_idents)
    return _fit_budget(repo_root, entries, focus, max_tokens)


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()


def _path_key(path: str) -> str:
    normalized = path.replace("\\", "/").removeprefix("./").rstrip("/")
    return normalized.casefold() if os.name == "nt" else normalized


def _normalize_hint(root: Path, hint: str) -> str:
    candidate = Path(hint).expanduser()
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            return candidate.as_posix()
    return PurePosixPath(hint.replace("\\", "/")).as_posix().removeprefix("./")


def _resolve_hints(root: Path, hints: list[str], files: list[str]) -> set[str]:
    available = {_path_key(path): path for path in files}
    by_basename: dict[str, list[str]] = defaultdict(list)
    for path in files:
        by_basename[_path_key(PurePosixPath(path).name)].append(path)

    resolved: set[str] = set()
    for hint in hints:
        if not hint:
            continue
        normalized = _normalize_hint(root, str(hint))
        exact = available.get(_path_key(normalized))
        if exact is not None:
            resolved.add(exact)
        elif "/" not in normalized:
            resolved.update(by_basename.get(_path_key(normalized), []))
    return resolved


def _source_files(root: Path) -> list[Path]:
    """Use Git's own exclude engine when available, including nested .gitignore rules."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        paths = [os.fsdecode(item) for item in result.stdout.split(b"\0") if item]
        return sorted(
            path
            for rel in paths
            if (path := root / Path(rel)).is_file()
            and not any(part in _SKIP_DIRS for part in Path(rel).parts)
        )
    except (OSError, subprocess.SubprocessError):
        return _walk_source_files(root)


def _walk_source_files(root: Path) -> list[Path]:
    patterns_by_dir: dict[str, list[tuple[str, str]]] = {".": []}
    result: list[Path] = []
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root).as_posix() or "."
        inherited = list(patterns_by_dir.get(rel_dir, []))
        ignore_file = current_path / ".gitignore"
        try:
            inherited.extend(
                (rel_dir, line)
                for line in ignore_file.read_text(
                    encoding="utf-8-sig", errors="replace"
                ).splitlines()
            )
        except OSError:
            pass
        patterns_by_dir[rel_dir] = inherited

        kept_dirs: list[str] = []
        for name in dirs:
            rel = (current_path / name).relative_to(root).as_posix()
            if name not in _SKIP_DIRS and not _ignored_by_patterns(rel, True, inherited):
                kept_dirs.append(name)
                patterns_by_dir[rel] = list(inherited)
        dirs[:] = kept_dirs

        for name in files:
            if name == ".gitignore":
                continue
            path = current_path / name
            rel = path.relative_to(root).as_posix()
            if not _ignored_by_patterns(rel, False, inherited):
                result.append(path)
    return sorted(result)


def _ignored_by_patterns(
    rel_path: str, is_dir: bool, patterns: list[tuple[str, str]]
) -> bool:
    ignored = False
    for base_dir, raw in patterns:
        pattern = raw.strip()
        if not pattern or pattern.startswith("#"):
            continue
        if pattern.startswith("\\#") or pattern.startswith("\\!"):
            pattern = pattern[1:]
        negate = pattern.startswith("!")
        if negate:
            pattern = pattern[1:]
        if not pattern:
            continue
        directory_only = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        anchored = pattern.startswith("/")
        pattern = pattern.lstrip("/")
        path = rel_path.replace("\\", "/")
        if base_dir != ".":
            prefix = base_dir + "/"
            if not path.startswith(prefix):
                continue
            path = path[len(prefix) :]
        parts = path.split("/")
        candidates = ["/".join(parts[:index]) for index in range(1, len(parts) + 1)]
        if is_dir:
            matched = any(_git_glob_match(item, pattern, anchored) for item in candidates)
        else:
            matched = any(
                _git_glob_match(item, pattern, anchored)
                for item in candidates[:-1]
            )
            if not matched and not directory_only:
                matched = _git_glob_match(path, pattern, anchored)
        if matched:
            ignored = not negate
    return ignored


def _git_glob_match(path: str, pattern: str, anchored: bool) -> bool:
    if anchored or "/" in pattern:
        path_parts = path.split("/")
        pattern_parts = pattern.split("/")

        def match_parts(path_index: int, pattern_index: int) -> bool:
            if pattern_index == len(pattern_parts):
                return path_index == len(path_parts)
            part = pattern_parts[pattern_index]
            if part == "**":
                return any(
                    match_parts(index, pattern_index + 1)
                    for index in range(path_index, len(path_parts) + 1)
                )
            if path_index == len(path_parts) or not fnmatch.fnmatchcase(
                path_parts[path_index], part
            ):
                return False
            return match_parts(path_index + 1, pattern_index + 1)

        return match_parts(0, 0)
    return any(fnmatch.fnmatchcase(part, pattern) for part in path.split("/"))


def _open_tag_cache(root: Path) -> sqlite3.Connection | None:
    try:
        cache_dir = root / "data" / "repomap"
        cache_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(cache_dir / "tags.sqlite3", timeout=5)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS tags ("
            "rel_path TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, payload TEXT NOT NULL)"
        )
        return connection
    except (OSError, sqlite3.Error):
        return None


def _get_tags_cached(
    connection: sqlite3.Connection | None,
    root: Path,
    rel_fname: str,
    path: Path,
    lang: str,
    mtime_ns: int,
) -> list[_Tag]:
    if connection is not None:
        try:
            row = connection.execute(
                "SELECT mtime_ns, payload FROM tags WHERE rel_path = ?", (rel_fname,)
            ).fetchone()
            if row and row[0] == mtime_ns:
                payload = json.loads(row[1])
                return [
                    _Tag(rel_fname, str(path), item[0], item[1], item[2])
                    for item in payload
                ]
        except (sqlite3.Error, TypeError, ValueError, json.JSONDecodeError):
            pass

    tags = _extract_tags(root, path, rel_fname, lang)
    if connection is not None:
        payload = [[tag.line, tag.name, tag.kind] for tag in tags]
        try:
            connection.execute(
                "INSERT INTO tags(rel_path, mtime_ns, payload) VALUES(?, ?, ?) "
                "ON CONFLICT(rel_path) DO UPDATE SET mtime_ns=excluded.mtime_ns, "
                "payload=excluded.payload",
                (rel_fname, mtime_ns, json.dumps(payload, ensure_ascii=False)),
            )
        except sqlite3.Error:
            pass
    return tags


def _extract_tags(root: Path, path: Path, rel_fname: str, lang: str) -> list[_Tag]:
    try:
        from grep_ast.tsl import get_language, get_parser
        from tree_sitter import Query
    except ImportError as exc:
        raise RuntimeError(
            "Repo maps require grep-ast, tree-sitter, and tree-sitter-language-pack."
        ) from exc

    query_source = TAG_QUERIES.get(lang)
    if not query_source:
        return []
    try:
        language = get_language(lang)
        parser = get_parser(lang)
        query = Query(language, query_source)
        code_bytes = path.read_bytes()
        code = code_bytes.decode("utf-8-sig", errors="replace")
        tree = parser.parse(code.encode("utf-8"))
        captures = _run_captures(query, tree.root_node)
    except (OSError, UnicodeError):
        return []
    except Exception:
        return []

    tags: list[_Tag] = []
    for capture, nodes in captures.items():
        if capture.startswith("name.definition."):
            kind = "def"
        elif capture.startswith("name.reference."):
            kind = "ref"
        else:
            continue
        for node in nodes:
            try:
                name = node.text.decode("utf-8", errors="replace")
            except (AttributeError, UnicodeError):
                continue
            tags.append(_Tag(rel_fname, str(path), node.start_point[0], name, kind))

    saw = {tag.kind for tag in tags}
    if "ref" in saw or "def" not in saw:
        return tags

    # Aider backfills references for definition-only queries with Pygments names.
    try:
        from pygments.lexers import guess_lexer_for_filename
        from pygments.token import Token

        lexer = guess_lexer_for_filename(str(path), code)
        for token_type, token_text in lexer.get_tokens(code):
            if token_type in Token.Name:
                tags.append(_Tag(rel_fname, str(path), -1, token_text, "ref"))
    except Exception:
        pass
    return tags


def _run_captures(query: Any, node: Any) -> dict[str, list[Any]]:
    # Aider supports tree-sitter's pre-0.24 and 0.24+ Query capture APIs.
    if hasattr(query, "captures"):
        return query.captures(node)
    from tree_sitter import QueryCursor

    return QueryCursor(query).captures(node)


def _ranked_entries(
    tags_by_file: dict[str, list[_Tag]],
    source_files: list[tuple[str, Path, str]],
    focus: set[str],
    mentioned_files: set[str],
    mentioned_idents: set[str],
) -> list[_Tag | _FileOnly]:
    defines: dict[str, set[str]] = defaultdict(set)
    references: dict[str, list[str]] = defaultdict(list)
    definitions: dict[tuple[str, str], set[_Tag]] = defaultdict(set)
    file_paths = {rel: path for rel, path, _lang in source_files}
    rel_fnames = sorted(file_paths)
    if not rel_fnames:
        return []

    personalization: dict[str, float] = {}
    per_file = 100.0 / len(rel_fnames)
    for rel_fname in rel_fnames:
        current = per_file if rel_fname in focus else 0.0
        if rel_fname in mentioned_files:
            current = max(current, per_file)
        components = set(PurePosixPath(rel_fname).parts)
        basename = PurePosixPath(rel_fname).name
        components.add(basename)
        components.add(Path(basename).stem)
        if components.intersection(mentioned_idents):
            current += per_file
        if current > 0:
            personalization[rel_fname] = current

        for tag in tags_by_file.get(rel_fname, []):
            if tag.kind == "def":
                defines[tag.name].add(rel_fname)
                definitions[(rel_fname, tag.name)].add(tag)
            elif tag.kind == "ref":
                references[tag.name].append(rel_fname)

    if not references:
        references = defaultdict(list, {name: list(paths) for name, paths in defines.items()})
    identifiers = set(defines).intersection(references)

    # Keep parallel symbol edges (including their identifier) as Aider does.
    edges: list[tuple[str, str, float, str]] = []
    nodes: set[str] = set()
    for ident in defines:
        if ident in references:
            continue
        for definer in defines[ident]:
            edges.append((definer, definer, 0.1, ident))
            nodes.add(definer)

    for ident in identifiers:
        definers = defines[ident]
        multiplier = 1.0
        is_snake = "_" in ident and any(char.isalpha() for char in ident)
        is_kebab = "-" in ident and any(char.isalpha() for char in ident)
        is_camel = any(char.isupper() for char in ident) and any(char.islower() for char in ident)
        if ident in mentioned_idents:
            multiplier *= 10.0
        if (is_snake or is_kebab or is_camel) and len(ident) >= 8:
            multiplier *= 10.0
        if ident.startswith("_"):
            multiplier *= 0.1
        if len(defines[ident]) > 5:
            multiplier *= 0.1

        for referencer, count in Counter(references[ident]).items():
            for definer in definers:
                weight = multiplier * math.sqrt(count)
                if referencer in focus:
                    weight *= 50.0
                edges.append((referencer, definer, weight, ident))
                nodes.add(referencer)
                nodes.add(definer)

    ranks = _pagerank(nodes, edges, personalization)
    ranked_definitions: dict[tuple[str, str], float] = defaultdict(float)
    outgoing: dict[str, float] = defaultdict(float)
    for src, _dst, weight, _ident in edges:
        outgoing[src] += weight
    for src, dst, weight, ident in edges:
        total = outgoing[src]
        if total:
            ranked_definitions[(dst, ident)] += ranks.get(src, 0.0) * weight / total

    ranked_tags: list[_Tag] = []
    ordered_defs = sorted(
        ranked_definitions.items(), reverse=True, key=lambda item: (item[1], item[0])
    )
    for (fname, ident), _rank in ordered_defs:
        ranked_tags.extend(sorted(definitions.get((fname, ident), ()), key=lambda tag: tag.line))

    included = {tag.rel_fname for tag in ranked_tags}
    for fname in sorted(nodes, key=lambda item: (ranks.get(item, 0.0), item), reverse=True):
        if fname in file_paths and fname not in included:
            ranked_tags.append(_FileOnly(fname, str(file_paths[fname])))
            included.add(fname)
    for fname in rel_fnames:
        if fname not in included:
            ranked_tags.append(_FileOnly(fname, str(file_paths[fname])))
    return ranked_tags


def _pagerank(
    nodes: set[str], edges: list[tuple[str, str, float, str]], personalization: dict[str, float]
) -> dict[str, float]:
    """Aider's NetworkX weighted PageRank, using the same damping and convergence bound."""
    if not nodes:
        return {}
    ordered = sorted(nodes)
    size = len(ordered)
    if personalization:
        total = sum(max(0.0, personalization.get(node, 0.0)) for node in ordered)
        if total > 0:
            base = {node: max(0.0, personalization.get(node, 0.0)) / total for node in ordered}
        else:
            base = {node: 1.0 / size for node in ordered}
    else:
        base = {node: 1.0 / size for node in ordered}

    weighted: dict[str, dict[str, float]] = {node: defaultdict(float) for node in ordered}
    for src, dst, weight, _ident in edges:
        if src in weighted and dst in nodes and weight > 0:
            weighted[src][dst] += weight
    totals = {node: sum(weighted[node].values()) for node in ordered}
    dangling = {node for node in ordered if totals[node] == 0.0}
    rank = dict(base)
    damping = 0.85
    for _ in range(100):
        dangling_sum = sum(rank[node] for node in dangling)
        next_rank = {
            node: (1.0 - damping) * base[node] + damping * dangling_sum * base[node]
            for node in ordered
        }
        for src in ordered:
            total = totals[src]
            if total <= 0:
                continue
            share = damping * rank[src] / total
            for dst, weight in weighted[src].items():
                next_rank[dst] += share * weight
        error = sum(abs(next_rank[node] - rank[node]) for node in ordered)
        rank = next_rank
        if error < size * 1e-6:
            break
    return rank


def _fit_budget(
    root: Path, entries: list[_Tag | _FileOnly], focus: set[str], max_tokens: int
) -> str:
    count = len(entries)
    if not count:
        return ""
    lower = 0
    upper = count
    middle = min(max_tokens // 25, count)
    best = ""
    best_tokens = 0
    render_cache: dict[tuple[str, tuple[int, ...], int], str] = {}
    context_cache: dict[str, tuple[int, Any]] = {}

    while lower <= upper:
        tree = _render_tree(root, entries[:middle], focus, render_cache, context_cache)
        tokens = _token_count(tree)
        pct_error = abs(tokens - max_tokens) / max_tokens
        if tokens <= max_tokens:
            if tokens > best_tokens:
                best = tree
                best_tokens = tokens
            if pct_error < 0.15:
                break
        if tokens < max_tokens:
            lower = middle + 1
        else:
            upper = middle - 1
        middle = (lower + upper) // 2
    return best


def _render_tree(
    root: Path,
    entries: list[_Tag | _FileOnly],
    focus: set[str],
    render_cache: dict[tuple[str, tuple[int, ...], int], str],
    context_cache: dict[str, tuple[int, Any]],
) -> str:
    if not entries:
        return ""
    selected: dict[str, tuple[Path, set[int], bool]] = {}
    for entry in entries:
        rel = entry.rel_fname
        if rel in focus:
            continue
        if isinstance(entry, _Tag):
            path, lines, has_tags = selected.setdefault(rel, (Path(entry.fname), set(), True))
            lines.add(entry.line)
            selected[rel] = (path, lines, has_tags)
        else:
            selected.setdefault(rel, (Path(entry.fname), set(), False))

    output: list[str] = []
    for rel in sorted(selected):
        path, lines, has_tags = selected[rel]
        if has_tags:
            try:
                mtime_ns = path.stat().st_mtime_ns
            except OSError:
                continue
            line_key = tuple(sorted(lines))
            key = (rel, line_key, mtime_ns)
            rendered = render_cache.get(key)
            if rendered is None:
                rendered = _render_context(path, rel, line_key, mtime_ns, context_cache)
                render_cache[key] = rendered
            output.extend(("", f"{rel}:", rendered))
        else:
            output.extend(("", rel))
    return "\n".join(output).lstrip("\n") + "\n"


def _render_context(
    path: Path, rel_fname: str, lines: tuple[int, ...], mtime_ns: int, cache: dict[str, tuple[int, Any]]
) -> str:
    try:
        from grep_ast import TreeContext
    except ImportError as exc:
        raise RuntimeError("Repo map rendering requires grep-ast.") from exc
    if rel_fname not in cache or cache[rel_fname][0] != mtime_ns:
        try:
            code = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return ""
        if not code.endswith("\n"):
            code += "\n"
        context = TreeContext(
            rel_fname,
            code,
            color=False,
            line_number=False,
            child_context=False,
            last_line=False,
            margin=0,
            mark_lois=False,
            loi_pad=0,
            show_top_of_file_parent_scope=False,
        )
        cache[rel_fname] = (mtime_ns, context)
    context = cache[rel_fname][1]
    context.lines_of_interest = set()
    context.add_lines_of_interest(lines)
    context.add_context()
    rendered = context.format()
    return "\n".join(line[:100] for line in rendered.splitlines())


def _token_count(text: str) -> int:
    """Conservative tokenizer estimate for common code and multilingual comments."""
    total = 0
    for part in _TOKEN_PARTS.findall(text):
        if part.isascii() and (part[0].isalnum() or part[0] == "_"):
            total += max(1, math.ceil(len(part) / 3))
        else:
            total += max(1, len(part))
    return total


__all__ = ["REPOMAP_TOOL_SPEC", "build_repo_map"]
