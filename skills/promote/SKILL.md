---
name: promote
description: Trigger an environment promotion from the CLI. Usage: /promote <from-env> [->] <to-env>
---

# /promote

Trigger a deployment promotion from one environment to another.

## Usage

```
/promote local preview
/promote local -> preview
/promote staging -> production
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `RUNWAY_DASHBOARD_URL` | no | Base URL of the runway router (e.g. `http://127.0.0.1:8000`). If unset, falls back to in-process promotion. |
| `RUNWAY_DASHBOARD_TOKEN` | no | Bearer token for the runway router. Required if `RUNWAY_DASHBOARD_URL` is set. |

## Behaviour

When `RUNWAY_DASHBOARD_URL` is set, the skill POSTs to `${RUNWAY_DASHBOARD_URL}/api/admin/runway/promote` with a JSON body `{"from_env": "...", "to_env": "...", "actor": ""}` and a `Authorization: Bearer <RUNWAY_DASHBOARD_TOKEN>` header.

When `RUNWAY_DASHBOARD_URL` is unset, the skill imports `runway.engine.PromotionEngine` and calls `promote()` in-process.

Exit 0 on success, exit 1 on failure.
