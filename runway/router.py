"""Read-only FastAPI router for runway environment state."""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from runway.config import ConfigError, get_environment, load_environments
from runway.state import read_state

_ENV_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,40}$")


def create_runway_router(
    project_root: Path,
    auth_dependency: Callable | None = None,
    mount_prefix: str = "/api/admin/runway",
) -> APIRouter:
    if auth_dependency is None:
        raise RuntimeError(
            "kv-runway router refuses to mount without auth_dependency"
        )

    router = APIRouter(prefix=mount_prefix)

    @router.get("/environments", dependencies=[Depends(auth_dependency)])
    async def list_environments():
        config = load_environments(project_root)
        state = read_state(project_root)
        result = []
        for env in config.environments:
            entry = state.get(env.name)
            result.append({
                "name": env.name,
                "type": env.type.value,
                "status": entry.status.value if entry else "unknown",
                "locked_by": entry.lock.actor if (entry and entry.lock) else None,
            })
        return result

    @router.get("/environments/{name}", dependencies=[Depends(auth_dependency)])
    async def get_environment_detail(name: str):
        if not _ENV_NAME_RE.match(name):
            raise HTTPException(status_code=422, detail=f"Invalid environment name: {name!r}")
        try:
            config = load_environments(project_root)
            get_environment(config, name)
        except ConfigError as exc:
            raise HTTPException(status_code=404, detail=f"Environment {name!r} not found") from exc
        state = read_state(project_root)
        entry = state.get(name)
        return {
            "name": name,
            "type": next(e.type.value for e in config.environments if e.name == name),
            "status": entry.status.value if entry else "unknown",
            "lock": entry.lock.model_dump(mode="json") if (entry and entry.lock) else None,
            "current": entry.current.model_dump(mode="json") if (entry and entry.current) else None,
        }

    @router.get("/health")
    async def health():
        return {"ok": True}

    return router
