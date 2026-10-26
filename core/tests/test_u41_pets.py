from __future__ import annotations

import io
import json
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from atlas.api import pets_router
from atlas.pet_store import PetPackageError, PetStore


def _archive(manifest: dict, avatar: bytes | None = None) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        if avatar is not None:
            archive.writestr("assets/avatar.png", avatar)
    return stream.getvalue()


def test_pet_store_hatch_import_switch_remove_and_validate_paths(tmp_path):
    store = PetStore(tmp_path / "pets")
    hatched = store.hatch("小云", "☁️", "#3366aa")
    assert store.active()["id"] == hatched["id"]
    assert (tmp_path / "pets" / "packages" / hatched["id"] / "manifest.json").is_file()

    manifest = {"id": "local-fox", "name": "本地狐狸", "emoji": "🦊", "color": "#aa6633", "avatar": "assets/avatar.png"}
    installed = store.install_archive(_archive(manifest, b"\x89PNG\r\n\x1a\nminimal-test-png"))
    assert installed["name"] == "本地狐狸"
    assert store.avatar_path("local-fox").read_bytes().startswith(b"\x89PNG")
    assert store.activate("local-fox")["id"] == "local-fox"
    store.remove("local-fox")
    assert store.active()["id"] == "atlas-companion"

    with pytest.raises(PetPackageError, match="路径"):
        store.install_archive(_archive({"id": "bad", "name": "坏包", "avatar": "../escape.png"}))
    with pytest.raises(PetPackageError, match="符号链接"):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = (0o120777 << 16)
            archive.writestr(info, "../../outside")
            archive.writestr("manifest.json", json.dumps({"id": "badlink", "name": "坏链接"}))
        store.install_archive(stream.getvalue())


def test_pet_api_hatch_upload_activate_and_remove(tmp_path, monkeypatch):
    monkeypatch.setattr(pets_router, "_store", PetStore(tmp_path / "api-pets"))
    app = FastAPI()
    app.include_router(pets_router.router)
    with TestClient(app) as client:
        created = client.post("/api/pets/hatch", json={"name": "Api Cat", "emoji": "🐈", "color": "#8277f4"})
        assert created.status_code == 200
        pet_id = created.json()["pet"]["id"]
        assert created.json()["active_id"] == pet_id

        archive = _archive({"id": "zip-pet", "name": "Zip Pet", "emoji": "🐉", "color": "#227755"})
        response = client.post("/api/pets/install", files={"file": ("pet.zip", archive, "application/zip")})
        assert response.status_code == 200
        assert any(pet["id"] == "zip-pet" for pet in response.json()["pets"])
        assert client.put("/api/pets/zip-pet/active").json()["active_id"] == "zip-pet"
        removed = client.delete("/api/pets/zip-pet")
        assert removed.status_code == 200
        assert removed.json()["active_id"] == "atlas-companion"

