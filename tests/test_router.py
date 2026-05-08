"""Tests for runway.router — read-only FastAPI router."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from runway.router import create_runway_router

_ENVIRONMENTS_JSON = {
    "project": "test-project",
    "environments": [
        {"name": "preview", "type": "ephemeral"},
        {"name": "staging", "type": "persistent"},
    ],
}


def _write_env_config(tmp_path: Path) -> None:
    runway_dir = tmp_path / ".runway"
    runway_dir.mkdir()
    (runway_dir / "environments.json").write_text(
        json.dumps(_ENVIRONMENTS_JSON), encoding="utf-8"
    )


def _fake_auth():
    return True


def _make_client(tmp_path: Path) -> TestClient:
    _write_env_config(tmp_path)
    router = create_runway_router(tmp_path, auth_dependency=_fake_auth)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _require_token(x_token: str = Header(None)):
    if x_token != "secret":
        raise HTTPException(status_code=401)


def _make_client_with_real_auth(tmp_path: Path) -> TestClient:
    _write_env_config(tmp_path)
    router = create_runway_router(tmp_path, auth_dependency=_require_token)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_router_without_auth_raises(tmp_path):
    with pytest.raises(RuntimeError, match="refuses to mount without auth_dependency"):
        create_runway_router(tmp_path)


def test_health_returns_200_no_auth(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/admin/runway/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_list_environments_200(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/admin/runway/environments")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2
    names = {item["name"] for item in data}
    assert names == {"preview", "staging"}
    for item in data:
        assert "type" in item
        assert "status" in item
        assert "locked_by" in item


def test_list_environments_401_without_auth(tmp_path):
    client = _make_client_with_real_auth(tmp_path)
    resp = client.get("/api/admin/runway/environments")
    assert resp.status_code == 401


def test_get_environment_detail_200(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/admin/runway/environments/preview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "preview"
    assert data["type"] == "ephemeral"
    assert "status" in data
    assert "lock" in data
    assert "current" in data


def test_get_environment_detail_404(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/admin/runway/environments/nonexistent")
    assert resp.status_code == 404


def test_get_environment_detail_422_invalid_name(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/admin/runway/environments/INVALID_NAME")
    assert resp.status_code == 422
