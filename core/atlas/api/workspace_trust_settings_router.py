"""Read and revoke locally persisted workspace rule trust.

These routes only update the trust registry. Runtime approval events remain
owned by ``run_drive`` and are not created, answered, or modified here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


def _server() -> Any:
    import atlas.server

    return atlas.server


def _local_root_key(root: str) -> str:
    """Return the same canonical key used by local workspace rule loading."""
    if not root or "://" in root or root.startswith(("\\\\", "//")):
        raise HTTPException(status_code=400, detail="只支持本机绝对工作区路径。")
    try:
        path = Path(root).expanduser()
        if not path.is_absolute():
            raise HTTPException(status_code=400, detail="工作区路径必须是本机绝对路径。")
        return str(path.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="工作区路径无效。") from exc


@router.get("/api/workspace/security/trust")
async def get_local_workspace_trust(root: str) -> dict[str, Any]:
    """Report whether one canonical local workspace root is trusted."""
    root_key = _local_root_key(root)
    trusted = bool(_server()._workspace_trust().get(root_key, False))
    return {"root": root_key, "trusted": trusted}


@router.delete("/api/workspace/security/trust")
async def revoke_local_workspace_trust(root: str) -> dict[str, Any]:
    """Revoke future rule loading for one local workspace root only."""
    root_key = _local_root_key(root)
    trust = _server()._workspace_trust()
    revoked = bool(trust.get(root_key, False))
    if revoked:
        # Reuse the canonical atomic persistence helper used by runtime consent.
        # This does not resolve or answer any pending rules.trust_required event.
        _server()._set_workspace_trusted(root_key, False)
    return {"root": root_key, "trusted": False, "revoked": revoked}
