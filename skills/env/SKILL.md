---
name: env
description: View and manage environment state from the CLI. Subcommands: /env status, /env lock release <env>
---

# /env

View environment state and manage locks.

## Subcommands

### status
Print one line per environment: `name | type | status | locked_by`

### lock release <env>
Release a stale lock on an environment. Prompts for confirmation before executing.

## Usage

```
/env status
/env lock release staging
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `RUNWAY_DASHBOARD_URL` | no | Base URL of the runway router. If set, reads state via the router. If unset, reads directly from disk. |
| `RUNWAY_DASHBOARD_TOKEN` | no | Bearer token for the runway router. |
| `RUNWAY_PROJECT_ROOT` | no | Path to the project root (default: current directory). |
