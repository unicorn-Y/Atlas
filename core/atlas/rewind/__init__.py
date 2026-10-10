# Behavior from Claude Code v2.1.296 docs: https://code.claude.com/docs/en/checkpointing
# Snapshot and message-boundary behavior translated from OpenCode
# packages/opencode/src/snapshot/index.ts and packages/opencode/src/session/revert.ts
# at anomalyco/opencode commit 055d95bb7e278c94baf06235a52cac79dd13ba67 (MIT).
# File change statuses and structured unified-diff behavior translated from
# openai/codex codex-rs/git-utils/src/baseline.rs at commit
# 806d9732c974bc8a51b8317c1bd8985544fe627c (Apache-2.0). Git command helpers in
# codex-rs/git-utils/src/operations.rs were reviewed; no Git subprocess is needed
# because the existing byte snapshot store is the authoritative code snapshot.

"""Conversation-bound workspace checkpoints and three-mode rewind operations.

The byte snapshots remain owned by :class:`ShadowGitCheckpointStore`. This module
adds a small manifest binding to each snapshot and leaves conversation storage
behind injected callbacks so a later integration can choose its own authority.
"""

from __future__ import annotations

import difflib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from ..agent.checkpoints import ShadowGitCheckpointStore

RewindMode = Literal["code", "conversation", "both"]
ConversationPosition = Callable[[str], str | None]
ConversationTruncator = Callable[[str, str | None], object]


@dataclass(frozen=True, slots=True)
class RewindPoint:
    """One workspace snapshot bound to a conversation turn."""

    point_id: str
    conversation_id: str
    turn_id: str
    workspace: str
    created_at: str
    after_message_id: str | None


@dataclass(frozen=True, slots=True)
class RewindFileChange:
    """A path changed since a checkpoint, using Git-style status labels."""

    path: str
    status: Literal["added", "modified", "deleted"]
    binary: bool = False


@dataclass(frozen=True, slots=True)
class RewindPreview:
    """Files and unified diff that a code rewind would change."""

    point_id: str
    files: list[str]
    diff: str
    changes: list[RewindFileChange]


@dataclass(frozen=True, slots=True)
class RewindResult:
    """Completed portions of a requested rewind."""

    point_id: str
    mode: RewindMode
    restored_files: list[str]
    conversation_truncated: bool
    after_message_id: str | None


class RewindManager:
    """Bind byte snapshots to turns and delegate conversation truncation.

    ``conversation_position`` reads the last message id before a turn starts.
    ``truncate_conversation`` is called only for conversation or combined rewind;
    neither callback is connected to Atlas' conversation database by default.
    """

    def __init__(
        self,
        store: ShadowGitCheckpointStore | None = None,
        *,
        conversation_position: ConversationPosition | None = None,
        truncate_conversation: ConversationTruncator | None = None,
    ) -> None:
        self.store = store or ShadowGitCheckpointStore()
        self.conversation_position = conversation_position
        self.truncate_conversation = truncate_conversation

    def checkpoint_before_turn(
        self,
        conversation_id: str,
        turn_id: str,
        workspace: str,
        *,
        after_message_id: str | None = None,
    ) -> str:
        """Capture the workspace and bind it to the current conversation turn.

        ``after_message_id`` is the conversation tail before the turn begins. If
        omitted, an injected ``conversation_position`` callback may supply it.
        """
        if not conversation_id or not turn_id:
            raise ValueError("conversation_id and turn_id must be non-empty")
        if after_message_id is None and self.conversation_position is not None:
            after_message_id = self.conversation_position(conversation_id)
        if after_message_id is not None and not isinstance(after_message_id, str):
            raise TypeError("after_message_id must be a string or None")

        manifest = self.store.create_checkpoint(
            workspace,
            ["."],
            run_id=turn_id,
            conversation_id=conversation_id,
        )
        manifest["turn_id"] = turn_id
        manifest["after_message_id"] = after_message_id
        self._write_manifest(manifest["id"], manifest)
        return str(manifest["id"])

    def list_points(self, conversation_id: str) -> list[RewindPoint]:
        """List bound checkpoints for one conversation, newest first."""
        if not conversation_id:
            raise ValueError("conversation_id must be non-empty")
        points: list[RewindPoint] = []
        for item in self.store.list_checkpoints():
            if item.get("conversation_id") != conversation_id:
                continue
            manifest = self._read_manifest(str(item["id"]))
            turn_id = manifest.get("turn_id")
            if not isinstance(turn_id, str):
                continue
            points.append(self._point(manifest, turn_id))
        return sorted(points, key=lambda point: point.created_at, reverse=True)

    def preview(self, point_id: str) -> RewindPreview:
        """Compare the selected byte snapshot with the current scoped workspace."""
        manifest = self._read_manifest(point_id)
        workspace = Path(str(manifest["workspace"])).resolve()
        before = self._snapshot_files(point_id, manifest, workspace)
        after = self._current_files(manifest, workspace)

        changes: list[RewindFileChange] = []
        diff_parts: list[str] = []
        for relative in sorted(before.keys() | after.keys()):
            old = before.get(relative)
            new = after.get(relative)
            if old == new:
                continue
            status: Literal["added", "modified", "deleted"]
            if old is None:
                status = "added"
            elif new is None:
                status = "deleted"
            else:
                status = "modified"
            binary = self._is_binary(old) or self._is_binary(new)
            changes.append(RewindFileChange(relative, status, binary))
            diff_parts.append(self._render_file_diff(relative, old, new, binary))

        return RewindPreview(
            point_id=point_id,
            files=[change.path for change in changes],
            diff="".join(diff_parts),
            changes=changes,
        )

    def rewind(self, point_id: str, mode: RewindMode) -> RewindResult:
        """Restore code, truncate conversation, or perform both operations."""
        if mode not in ("code", "conversation", "both"):
            raise ValueError(f"unsupported rewind mode: {mode}")
        manifest = self._read_manifest(point_id)
        conversation_id = manifest.get("conversation_id")
        after_message_id = manifest.get("after_message_id")
        wants_conversation = mode in ("conversation", "both")
        if wants_conversation:
            if self.truncate_conversation is None:
                raise RuntimeError("truncate_conversation callback is not configured")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise ValueError("checkpoint has no conversation binding")
            if after_message_id is not None and not isinstance(after_message_id, str):
                raise ValueError("checkpoint has an invalid message boundary")

        restored_files: list[str] = []
        if mode in ("code", "both"):
            preview = self.preview(point_id)
            restored_files = preview.files
            self.store.restore_checkpoint(point_id)
            self._remove_added_files(manifest, preview.changes)

        if wants_conversation:
            self.truncate_conversation(conversation_id, after_message_id)

        return RewindResult(
            point_id=point_id,
            mode=mode,
            restored_files=restored_files,
            conversation_truncated=wants_conversation,
            after_message_id=after_message_id if wants_conversation else None,
        )

    def _read_manifest(self, point_id: str) -> dict[str, object]:
        path = self.store.manifest_path(point_id)
        if path is None:
            raise KeyError(point_id)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("id") != point_id:
            raise ValueError(f"invalid checkpoint manifest: {point_id}")
        return manifest

    def _write_manifest(self, point_id: str, manifest: dict[str, object]) -> None:
        path = self.store.manifest_path(point_id)
        if path is None:
            raise KeyError(point_id)
        temporary = path.with_name(f"manifest.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _point(manifest: dict[str, object], turn_id: str) -> RewindPoint:
        return RewindPoint(
            point_id=str(manifest["id"]),
            conversation_id=str(manifest["conversation_id"]),
            turn_id=turn_id,
            workspace=str(manifest["workspace"]),
            created_at=str(manifest["created_at"]),
            after_message_id=(
                manifest.get("after_message_id")
                if isinstance(manifest.get("after_message_id"), str)
                else None
            ),
        )

    def _snapshot_files(
        self, point_id: str, manifest: dict[str, object], workspace: Path
    ) -> dict[str, bytes]:
        snapshot = self.store.storage_dir / point_id
        items = manifest.get("files", [])
        if not isinstance(items, list):
            raise ValueError(f"invalid checkpoint file list: {point_id}")
        files: dict[str, bytes] = {}
        for item in items:
            if not isinstance(item, dict) or not item.get("exists") or item.get("directory"):
                continue
            relative = self._safe_relative(workspace, item.get("path"))
            source = snapshot / "git" / Path(relative)
            if not source.is_file():
                source = snapshot / "files" / Path(relative)
            if not source.is_file():
                raise FileNotFoundError(f"snapshot bytes missing for {relative}")
            files[relative] = source.read_bytes()
        return files

    def _current_files(self, manifest: dict[str, object], workspace: Path) -> dict[str, bytes]:
        scopes = manifest.get("scopes", [])
        if not isinstance(scopes, list):
            raise ValueError("invalid checkpoint scopes")
        files: dict[str, bytes] = {}
        for scope in scopes:
            if not isinstance(scope, dict):
                continue
            raw_path = scope.get("path")
            scoped = workspace / Path(str(raw_path))
            resolved_scope = scoped.resolve()
            if resolved_scope != workspace and workspace not in resolved_scope.parents:
                raise ValueError("checkpoint scope escapes the workspace")
            if scoped.is_file():
                candidates = [scoped]
            elif scoped.is_dir():
                candidates = scoped.rglob("*")
            else:
                continue
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                resolved = candidate.resolve()
                if resolved != workspace and workspace not in resolved.parents:
                    continue
                if self.store._excluded_file(resolved, workspace):
                    continue
                relative = candidate.relative_to(workspace).as_posix()
                files[relative] = candidate.read_bytes()
        return files

    @staticmethod
    def _remove_added_files(
        manifest: dict[str, object], changes: list[RewindFileChange]
    ) -> None:
        """Remove new files the byte store cannot prune at a workspace-root scope."""
        workspace = Path(str(manifest["workspace"])).resolve()
        for change in changes:
            if change.status != "added":
                continue
            target = workspace / Path(change.path)
            resolved = target.resolve()
            if resolved != workspace and workspace not in resolved.parents:
                raise ValueError("rewind path escapes the workspace")
            if target.is_file() or target.is_symlink():
                target.unlink()

    @staticmethod
    def _safe_relative(workspace: Path, value: object) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError("invalid checkpoint path")
        relative = Path(value)
        if relative.is_absolute():
            raise ValueError("checkpoint path must be relative")
        resolved = (workspace / relative).resolve()
        if resolved != workspace and workspace not in resolved.parents:
            raise ValueError("checkpoint path escapes the workspace")
        return resolved.relative_to(workspace).as_posix()

    @staticmethod
    def _is_binary(content: bytes | None) -> bool:
        if content is None:
            return False
        if b"\0" in content:
            return True
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return True
        return False

    @classmethod
    def _render_file_diff(
        cls, path: str, before: bytes | None, after: bytes | None, binary: bool
    ) -> str:
        if binary:
            return f"Binary files a/{path} and b/{path} differ\n"
        old = (before or b"").decode("utf-8").splitlines(keepends=True)
        new = (after or b"").decode("utf-8").splitlines(keepends=True)
        return "".join(
            difflib.unified_diff(
                old,
                new,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="\n",
            )
        )


_default_manager = RewindManager()


def checkpoint_before_turn(
    conversation_id: str,
    turn_id: str,
    workspace: str,
    *,
    after_message_id: str | None = None,
) -> str:
    """Create a pre-turn checkpoint with the default byte snapshot store."""
    return _default_manager.checkpoint_before_turn(
        conversation_id,
        turn_id,
        workspace,
        after_message_id=after_message_id,
    )


def list_points(conversation_id: str) -> list[RewindPoint]:
    """List pre-turn checkpoints for a conversation."""
    return _default_manager.list_points(conversation_id)


def preview(point_id: str) -> RewindPreview:
    """Preview changed paths and text diff for a checkpoint."""
    return _default_manager.preview(point_id)


def rewind(
    point_id: str,
    mode: RewindMode,
    *,
    truncate_conversation: ConversationTruncator | None = None,
) -> RewindResult:
    """Rewind through the default store, optionally injecting conversation truncation."""
    if truncate_conversation is None:
        return _default_manager.rewind(point_id, mode)
    return RewindManager(
        store=_default_manager.store,
        truncate_conversation=truncate_conversation,
    ).rewind(point_id, mode)


__all__ = [
    "ConversationPosition",
    "ConversationTruncator",
    "RewindFileChange",
    "RewindManager",
    "RewindMode",
    "RewindPoint",
    "RewindPreview",
    "RewindResult",
    "checkpoint_before_turn",
    "list_points",
    "preview",
    "rewind",
]
