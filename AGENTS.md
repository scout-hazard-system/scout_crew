# AGENTS.md — scout_crew

## What this is

The local Scout crew/agent backend: a Python package (`scout_crew`) with a CLI (`bin/scout`), a legacy Qt
GUI (`bin/scout-gui`, retiring after React parity), the blackboard HTTP store (`src/scout_crew/blackboard/`),
and local/mesh LLM wiring. Apache-2.0 (`LICENSE` / `NOTICE` / `LICENSES/`).

> Note to agents: this file **replaces** the old auto-generated `crewai create` reference. scout_crew is no
> longer a CrewAI-scaffolded project and CrewAI docs are not the project guide. Keep CrewAI-scaffolding
> patterns out of new work; the routing home repo is `routing-scouting-app-to-be-named`.

## Layout

```
src/scout_crew/
  main.py, cli.py            SCOTT CLI entry (`scout ...`): status, roster, models, chat, crew, env, dev
  crew.py, admin_policy.py   orchestration + admin/specialist loop policy
  gui.py                     legacy PySide6 desktop GUI (CrewAI-era controls, being retired)
  local_llms.py              per-role Ollama OpenAI-compatible LLM wiring (mesh-aware since kepler/cross-host-paths)
  prompt_syntax.py           strict prompt format: TASK: <MODE>\nTranscript: ...
  arizona_phase.py           AZ hazard/coverage phase logic
  blackboard/{server,client,store}.py   HTTP blackboard :8765, category-scoped + ACL
  tools/{blackboard_tool,custom_tool}.py
  config/{agents.yaml,tasks.yaml,arizona_phase.json}
bin/scout, bin/scout-gui, bin/scout-mesh-status
USAGE.md, SETUP.md, README.md, pyproject.toml + uv.lock (uv)
```

## Commands

```bash
uv sync
uv run scout status | roster | models | chat -m core | crew     # or ./bin/scout ...
uv run python -m scout_crew.blackboard.server                     # blackboard :8765
```

## Rules

- Mesh-aware: hub at `10.66.0.1`; LLM/blackboard/map urls come from mesh addresses, not LAN DHCP.
- Specialists use the strict `TASK: <MODE>\nTranscript: ...` format; free-form prompts are declined by alert/rank.
- Local-Ollama-only: every role routes through local engines; never configure remote LLM endpoints.
- Blackboard: category-scoped keys, per-role read/write ACLs, append-only audit; writes fail closed.
- Model version bumps are explicit and intentional (3rd digit) — see the routing home AGENTS.md.