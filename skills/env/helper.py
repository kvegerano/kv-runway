#!/usr/bin/env python3
"""
/env helper — show environment status and manage locks.

Usage:
    python helper.py status
    python helper.py lock release <env-name>
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _get_project_root() -> Path:
    return Path(os.environ.get("RUNWAY_PROJECT_ROOT", ".")).resolve()


def _cmd_status_local(project_root: Path) -> None:
    """Print status table from disk state."""
    try:
        from runway.config import load_environments
        from runway.state import read_state
    except ImportError as exc:
        print(f"Cannot import runway: {exc}", file=sys.stderr)
        sys.exit(1)

    config = load_environments(project_root)
    state = read_state(project_root)

    print(f"{'name':<20} {'type':<12} {'status':<12} {'locked_by'}")
    print("-" * 60)
    for env in config.environments:
        entry = state.get(env.name)
        status = entry.status.value if entry else "unknown"
        locked_by = (entry.lock.actor if (entry and entry.lock) else None) or "-"
        print(f"{env.name:<20} {env.type.value:<12} {status:<12} {locked_by}")


def _cmd_status_router(base_url: str, token: str) -> None:
    """Print status table from router."""
    try:
        import httpx
    except ImportError:
        print("httpx required for router mode.", file=sys.stderr)
        sys.exit(1)

    url = f"{base_url.rstrip('/')}/api/admin/runway/environments"
    try:
        response = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except httpx.RequestError as exc:
        print(f"Failed to reach router: {exc}", file=sys.stderr)
        sys.exit(1)

    if response.status_code != 200:
        print(f"Router returned {response.status_code}", file=sys.stderr)
        sys.exit(1)

    envs = response.json()
    print(f"{'name':<20} {'type':<12} {'status':<12} {'locked_by'}")
    print("-" * 60)
    for env in envs:
        locked_by = env.get("locked_by") or "-"
        print(f"{env['name']:<20} {env['type']:<12} {env['status']:<12} {locked_by}")


def _cmd_lock_release(env_name: str, project_root: Path) -> None:
    """Release a stale lock after user confirmation."""
    confirm = input(f"Release lock on {env_name!r}? [y/N] ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        sys.exit(0)

    try:
        from runway.state import release_lock
    except ImportError as exc:
        print(f"Cannot import runway: {exc}", file=sys.stderr)
        sys.exit(1)

    release_lock(project_root, env_name)
    print(f"Lock released for {env_name!r}.")


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv

    args = argv[1:]

    if not args:
        print("Usage: env status | env lock release <env>", file=sys.stderr)
        sys.exit(1)

    dashboard_url = os.environ.get("RUNWAY_DASHBOARD_URL")
    dashboard_token = os.environ.get("RUNWAY_DASHBOARD_TOKEN", "")
    project_root = _get_project_root()

    if args[0] == "status":
        if dashboard_url:
            _cmd_status_router(dashboard_url, dashboard_token)
        else:
            _cmd_status_local(project_root)

    elif args[0] == "lock" and len(args) == 3 and args[1] == "release":
        env_name = args[2]
        _cmd_lock_release(env_name, project_root)

    else:
        print(f"Unknown subcommand: {' '.join(args)}", file=sys.stderr)
        print("Usage: env status | env lock release <env>", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
