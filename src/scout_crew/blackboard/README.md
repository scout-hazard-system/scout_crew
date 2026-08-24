# Scout categorized blackboard (multi-machine)

**License:** Apache License, Version 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

Shared memory for CrewAI agents across hosts.

## Categories

| Category | Purpose | Writers | Readers |
|----------|---------|---------|---------|
| `pipeline` | General pipeline facts | alert, intel, vet, rank, core (raw); **manager** (summary/rewrite only) | all roles + hermes |
| `dev_debug` | Dev debug / rewrite notes | **dev only** | dev, manager, hermes |

## Roles

- **Specialists + core** → write `pipeline` (`kind=raw`)
- **Manager** → read all; write `pipeline` only as `kind=summary` or `kind=rewrite` (succinct)
- **Dev** → write/read `dev_debug`; may read `pipeline`; never write `pipeline`
- **Hermes** → **read-only** on both categories

## Local mode

Default: SQLite at `data/blackboard/scout_blackboard.db` (WAL).

```bash
scout blackboard stats
scout blackboard write --role alert --category pipeline --title "stop" --body "ALERT: ..." --tags alert,az
scout blackboard read --role manager --category pipeline --limit 10
scout blackboard snapshot --role hermes
```

## Multi-machine mode

On the shared host (or any always-on node):

```bash
# bind on tailnet/LAN
python -m scout_crew.blackboard.server --host 0.0.0.0 --port 8765
```

On every crew machine:

```bash
export SCOUT_BLACKBOARD_URL=http://<server-tailscale-ip>:8765
# optional: also set in .env
```

All writers/readers then hit the same HTTP API (`/v1/write`, `/v1/read`, `/v1/snapshot`).

## CrewAI tools

Injected per agent via `tools_for_role(...)`:

- `blackboard_write`
- `blackboard_read`
- `blackboard_snapshot`

Hermes external agents should only be given read tools (see `tools_for_role("hermes")`).
