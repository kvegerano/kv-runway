#!/usr/bin/env python3
"""
/promote helper — parse args, run promotion (in-process or via router).

Usage:
    python helper.py <from-env> <to-env>
    python helper.py <from-env> -> <to-env>
    python helper.py <from-env> "<to-env>"
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _parse_args(argv: list[str]) -> tuple[str, str]:
    """Parse `from_env to_env` or `from_env -> to_env` from sys.argv[1:]."""
    args = argv[1:]
    if len(args) == 2 and args[1] != "->":
        return args[0], args[1]
    if len(args) == 3 and args[1] == "->":
        return args[0], args[2]
    print(f"Usage: {argv[0]} <from-env> [->] <to-env>", file=sys.stderr)
    sys.exit(1)


def _promote_via_router(from_env: str, to_env: str, base_url: str, token: str) -> None:
    """POST to the runway router promote endpoint."""
    try:
        import httpx
    except ImportError:
        print("httpx is required for router mode. Run: pip install httpx", file=sys.stderr)
        sys.exit(1)

    url = f"{base_url.rstrip('/')}/api/admin/runway/promote"
    try:
        response = httpx.post(
            url,
            json={"from_env": from_env, "to_env": to_env, "actor": ""},
            headers={"Authorization": f"Bearer {token}"},
            timeout=300,
        )
    except httpx.RequestError as exc:
        print(f"Failed to reach runway router at {base_url}: {exc}", file=sys.stderr)
        sys.exit(1)

    if response.status_code == 200:
        result = response.json()
        if result.get("success"):
            print(f"Promoted {from_env} → {to_env}: commit={result.get('commit', 'unknown')}")
            sys.exit(0)
        else:
            print(f"Promotion failed: step={result.get('failed_step')} reason={result.get('reason')}")
            sys.exit(1)
    else:
        print(f"Router returned {response.status_code}: {response.text}", file=sys.stderr)
        sys.exit(1)


def _promote_in_process(from_env: str, to_env: str, project_root: Path) -> None:
    """Import PromotionEngine and run promote() in-process."""
    try:
        from runway.engine import PromotionEngine
    except ImportError as exc:
        print(f"Cannot import runway.engine: {exc}", file=sys.stderr)
        print("Run: pip install kv-runway", file=sys.stderr)
        sys.exit(1)

    print(f"Promoting {from_env} → {to_env} (in-process)...")
    engine = PromotionEngine(project_root)
    result = engine.promote(from_env, to_env, actor="")

    if result.success:
        print(f"Success: commit={result.commit} duration={result.duration_seconds}s")
        sys.exit(0)
    else:
        print(f"Failed at step {result.failed_step!r}: {result.reason}")
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv
    from_env, to_env = _parse_args(argv)

    dashboard_url = os.environ.get("RUNWAY_DASHBOARD_URL")
    dashboard_token = os.environ.get("RUNWAY_DASHBOARD_TOKEN", "")

    print(f"Promoting: {from_env} → {to_env}")

    if dashboard_url:
        if not dashboard_token:
            print(
                "Warning: RUNWAY_DASHBOARD_URL is set but RUNWAY_DASHBOARD_TOKEN is empty. "
                "The router will likely return 401.",
                file=sys.stderr,
            )
        _promote_via_router(from_env, to_env, dashboard_url, dashboard_token)
    else:
        project_root = Path(os.environ.get("RUNWAY_PROJECT_ROOT", ".")).resolve()
        _promote_in_process(from_env, to_env, project_root)


if __name__ == "__main__":
    main()
