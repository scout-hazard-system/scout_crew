# Scout categorized blackboard (multi-machine)

**License:** Apache License, Version 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

Shared memory for CrewAI agents across hosts.

## Categories

| Category | Purpose | Writers | Readers |
|----------|---------|---------|---------|
| `pipeline` | General pipeline facts | alert, intel, vet, rank, core (raw); **manager** (summary/rewrite only) | all roles + hermes |
| `dev_debug` | Dev debug / rewrite notes | **dev only** | dev, manager, hermes |

**Sandbox pipeline policy** (`SCOUT_BLACKBOARD_SANDBOX_WRITERS`): when set on the
server, only the configured roles may post `pipeline` `kind=raw` entries — e.g.
the fleet sandbox defaults to `alert` (alert posts raw verdicts; the **manager
moderates** reads/audits and summary/rewrite entries). Unset → the default
role ACL above. This is config/doc-level scoping, not per-device isolation.

## Roles

- **Specialists + core** → write `pipeline` (`kind=raw`), subject to sandbox-writers
- **Manager** → read all; write `pipeline` only as `kind=summary` or `kind=rewrite` (succinct); mints tokens
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

## Key authorization (token auth) — framework

**No bootstrap or deploy-time minting.** Tokens are minted at runtime against
`SCOUT_BLACKBOARD_TOKEN_SECRET` (stdlib HMAC-SHA256, constant-time verify):
`scope`, `role`, `categories`, `device_id` (HTTPS-assigned, **no IMEI**), `iat`,
`exp`, `jti`. The manager moderates via audit + issue/revoke; there is **no hard
rate limit** — floods show up in `/v1/audit` volume and the manager acts.

| Endpoint | Gate | Purpose |
|----------|------|---------|
| `POST /v1/keys/authorize` | entry proof (`SCOUT_BLACKBOARD_ENTRY_TOKEN`) or captcha/network-presence marker | device onboarding → device-id assignment + role-scoped short-lived token; records `observed_ip` |
| `POST /v1/keys/issue` | `X-Scout-Admin` == secret | manager/CLI mints a role-scoped token |
| `POST /v1/keys/revoke` | `X-Scout-Admin` == secret | revoke by `jti` |
| `GET /v1/audit` | manager bearer token | audit log + per-token volume (flood watch) |

Read/write/snapshot require a category-scoped bearer token (reject if missing,
forged, expired, revoked, wrongly scoped, or role-mismatched). Android consumers
ship the in-app web-mirror + captcha proof in the secure-mesh-navigation app; the
server side here is the consumer-agnostic framework.
<!-- The proof seam above is intentionally server-side only for now. -->

```bash
# server (hub, file-backed) with auth + sandbox
export SCOUT_BLACKBOARD_TOKEN_SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
export SCOUT_BLACKBOARD_ENTRY_TOKEN=$(openssl rand -hex 16)
export SCOUT_BLACKBOARD_SANDBOX_WRITERS=alert
python -m scout_crew.blackboard.server --host 0.0.0.0 --port 8765

# device onboarding (proof-gated) -> role-scoped token + device id
scout blackboard authorize --entry-token "$SCOUT_BLACKBOARD_ENTRY_TOKEN" --role alert --device az-handheld

# manager moderation
scout blackboard issue-token --role manager --categories pipeline
scout blackboard audit --limit 200
scout blackboard revoke --jti <jti>
```

## Multi-machine mode

On the shared host (hub, e.g. the map-server hub `10.66.2.3`):

```bash
python -m scout_crew.blackboard.server --host 0.0.0.0 --port 8765
```

On every crew machine:

```bash
export SCOUT_BLACKBOARD_URL=http://10.66.2.3:8765
export SCOUT_BLACKBOARD_TOKEN=<role-scoped token>   # required when auth is on
# optional: also set in .env
```

All writers/readers then hit the same HTTP API (`/v1/write`, `/v1/read`, `/v1/snapshot`).

## Memory mode

`SCOUT_BLACKBOARD_MEMORY=1` (or `--memory`) runs the store in RAM
(`journal_mode=MEMORY`). Intended for per-peer sandbox contexts whose blackboard
context lives in the device RAM. The hub blackboard stays **file-backed** (SQLite
WAL) so shared facts survive restarts.

## CrewAI tools

Injected per agent via `tools_for_role(...)`:

- `blackboard_write`
- `blackboard_read`
- `blackboard_snapshot`
- `blackboard_issue_token` — **manager only** (mint, moderation path)
- `blackboard_audit` — **manager only** (audit + flood watch)

Hermes external agents should only be given read tools (see `tools_for_role("hermes")`).
Every role also gets the **read-only map tools** (`map_health`, `map_status`,
`map_shard`, `map_route_weather`) — agents query the hub map server but never
write geometry back to the blackboard.