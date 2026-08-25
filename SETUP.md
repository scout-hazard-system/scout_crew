# Scout Crew — Setup Process

**License:** Apache License, Version 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

End-to-end setup for the **local / Tailscale-mesh** multi-agent Scout stack (CrewAI + Ollama).

- **Source code:** Apache-2.0
- **Default model weights:** **Qwen3** (`qwen3:8b` and derived `scout-*` tags). Comply with applicable Qwen terms when downloading or serving weights.
- **Not in the default path:** Meta Llama weights / Llama Community License (this project does not ship them).
- **No cloud LLM tokens:** OpenAI-compatible traffic stays on loopback or private Tailscale peers (`:11434`). `assert_local_only()` refuses public cloud provider keys and non-mesh base URLs.

---

## 1. System prerequisites

| Tool | Why |
|------|-----|
| Linux desktop (Pop!_OS tested) | Specialists + optional crew host |
| Optional Windows peer | Serve `scout-hermes-hc*` over Tailscale |
| Python `>=3.10,<3.14` | CrewAI runtime |
| [uv](https://docs.astral.sh/uv/) | deps + tool runner |
| [Ollama](https://ollama.com) | local / mesh model server on `:11434` |
| Git | clone / updates |
| Tailscale (optional mesh) | multi-machine Hermes + blackboard |

```bash
# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"   # if needed

# Ollama on this machine
ollama serve    # if not already a systemd/user service
# For mesh: bind Ollama on 0.0.0.0:11434 (not only 127.0.0.1)
curl -s http://127.0.0.1:11434/api/tags | head
```

---

## 2. Model lineage and roster

### 2.1 Weight lineage

| Item | Value |
|------|--------|
| Base weights | `qwen3:8b` (Qwen3 family) |
| How Scout tags are built | Ollama **Modelfiles** (system prompt + params + no-think template for specialists) — not from-scratch pretraining |
| Reasoning / high-context | `scout-hermes-hc*` (also `FROM qwen3:8b`, thinking enabled) |
| Build script | `~/Desktop/llm/build/build_llm_set.sh` (`SCOUT_BASE_MODEL=qwen3:8b`) |
| Hermes build | `~/Desktop/llm/unified/build_hermes_hc.sh` |

### 2.2 Default role → model map

| Role | Ollama tag | Typical host |
|------|------------|--------------|
| Manager (admin) | `scout-hermes-hc1.0.0` / `scout-hermes-hc1.1.0` | Windows peer **or** local |
| Hermes (optional role) | same hermes-hc tags | Windows peer **or** local |
| Dev (admin) | `scout-dev` | Linux specialists host |
| Core | `scout-core1.0.5` | Linux |
| Alert | `scout-alert` | Linux |
| Intel | `scout-intel` | Linux |
| Vet | `scout-vet1.0.6` | Linux |
| Rank | `scout-rank` | Linux |
| Base fallback | `qwen3:8b` | Linux |

Fallbacks never prefer Llama. Status exposes `weight_lineage: "qwen3"`, `role_uses_llama`, and `leftover_llama_installs` (unused leftover Ollama tags only).

### 2.3 Build / refresh models

```bash
# Pull base once
ollama pull qwen3:8b

# Full specialist set (core, rank, vet, alert, intel, dev)
bash ~/Desktop/llm/build/build_llm_set.sh

# Hermes high-context (optional on this box; required on Windows if manager routes there)
bash ~/Desktop/llm/unified/build_hermes_hc.sh

ollama list | egrep 'scout-|qwen3:8b'
# Optional: remove unused legacy install
# ollama rm llama3.1
```

**Qwen3 note:** Specialists use a forced `/no_think` Modelfile template and higher `num_predict` / CrewAI `max_tokens` so short contracts (`VET_PASS`, `ALERT:…`) are not truncated by internal reasoning. Hermes keeps thinking enabled for director-style reasoning.

---

## 3. Project install

```bash
cd ~/Desktop/scout_crew
cp -n .env.example .env
# Prefer: uv sync / project venv
uv sync 2>/dev/null || crewai install

mkdir -p ~/.local/bin
ln -sfn "$PWD/bin/scout" ~/.local/bin/scout
ln -sfn "$PWD/bin/scout-gui" ~/.local/bin/scout-gui
ln -sfn "$PWD/bin/scout-mesh-status" ~/.local/bin/scout-mesh-status
hash -r
```

### 3.1 `.env` — single-machine (all models local)

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11434
OPENAI_API_KEY=ollama
OPENAI_API_BASE=http://127.0.0.1:11434/v1
OPENAI_BASE_URL=http://127.0.0.1:11434/v1

MODEL=ollama/qwen3:8b
OLLAMA_MODEL_MANAGER=ollama/scout-hermes-hc1.0.0
OLLAMA_MODEL_HERMES=ollama/scout-hermes-hc1.0.0
OLLAMA_MODEL_CORE=ollama/scout-core1.0.5
OLLAMA_MODEL_VET=ollama/scout-vet1.0.6
OLLAMA_MODEL_ALERT=ollama/scout-alert
OLLAMA_MODEL_INTEL=ollama/scout-intel
OLLAMA_MODEL_RANK=ollama/scout-rank
OLLAMA_MODEL_DEV=ollama/scout-dev
OLLAMA_MODEL_BASE=ollama/qwen3:8b

CREWAI_TRACING_ENABLED=true
```

### 3.2 `.env` — split mesh (Hermes on Windows, specialists on Linux)

Use when Windows Ollama serves hermes-hc and Linux serves the narrow specialists (verified pattern: Windows `100.82.130.47`, Linux `100.78.191.61`).

```bash
# Specialists / default host = this Linux machine
OLLAMA_BASE_URL=http://127.0.0.1:11434
OPENAI_API_KEY=ollama
OPENAI_API_BASE=http://127.0.0.1:11434/v1
OPENAI_BASE_URL=http://127.0.0.1:11434/v1

# Model pins (Qwen lineage)
OLLAMA_MODEL_MANAGER=ollama/scout-hermes-hc1.0.0
OLLAMA_MODEL_HERMES=ollama/scout-hermes-hc1.0.0
OLLAMA_MODEL_CORE=ollama/scout-core1.0.5
OLLAMA_MODEL_DEV=ollama/scout-dev
OLLAMA_MODEL_VET=ollama/scout-vet1.0.6
OLLAMA_MODEL_ALERT=ollama/scout-alert
OLLAMA_MODEL_INTEL=ollama/scout-intel
OLLAMA_MODEL_RANK=ollama/scout-rank
OLLAMA_MODEL_BASE=ollama/qwen3:8b

# Peer routing: manager + hermes resolve models on Windows
SCOUT_PEER_WINDOWS_IP=100.82.130.47
SCOUT_PEER_OLLAMA_OPENAI=http://100.82.130.47:11434/v1
OLLAMA_HOST_HERMES=http://100.82.130.47:11434
OLLAMA_HOST_MANAGER=http://100.82.130.47:11434
# Optional explicit specialist hosts (default = OLLAMA_BASE_URL)
# OLLAMA_HOST_CORE=http://127.0.0.1:11434
# OLLAMA_HOST_ALERT=http://127.0.0.1:11434

# Blackboard hub (usually Linux)
# SCOUT_BLACKBOARD_URL=http://100.78.191.61:8765
```

Per-role host env vars: `OLLAMA_HOST_MANAGER`, `OLLAMA_HOST_HERMES`, `OLLAMA_HOST_CORE`, `OLLAMA_HOST_DEV`, `OLLAMA_HOST_ALERT`, `OLLAMA_HOST_INTEL`, `OLLAMA_HOST_VET`, `OLLAMA_HOST_RANK`, `OLLAMA_HOST_BASE`.

Windows peer must:

1. Run Ollama reachable on Tailscale (`0.0.0.0:11434` or firewall allow).
2. Have `qwen3:8b` and `scout-hermes-hc*` installed.
3. Optionally drop unused `llama3.1` for a clean inventory.

```bash
scout-mesh-status
# expect: ollama TS win up; role endpoints show hermes/manager → Windows, specialists → Linux
```

Never commit `.env` (gitignored). Start from `.env.example`.

---

## 4. Architecture

```
User / GUI / CLI
      │
      ▼
prompt_syntax v1 envelope  (ADMIN-PRIVILEGED USER QUERY)
      │
      ├─ scout chat|dev  → single role model (host-aware)
      │
      └─ scout crew (sequential, no hierarchical planner)
            1 alert → 2 intel → 3 vet → 4 rank → 5 core
            6 dev (admin) → 7 manager synthesis (admin / hermes-hc)
```

| Concern | Implementation |
|---------|----------------|
| Local + mesh LLMs | `local_llms.py` (`make_llm`, `resolve_role_host`, `role_endpoints`) |
| Qwen-only prefs | `ROLE_MODEL_PREFS` — no Llama fallbacks |
| Anti-recursion | sequential process, `planning=False`, `memory=False`, DAG check |
| Admin user prompts | `prompt_syntax.py` + `admin_policy.py` |
| Alpha AZ scope | `arizona_phase.py` + `config/arizona_phase.json` |
| Blackboard | `blackboard/` + `tools_for_role` ACL |
| Traces | `CREWAI_TRACING_ENABLED=true` (models still local/mesh) |

---

## 5. Verify install

### 5.1 Health and roster

```bash
scout status
# expect:
#   ollama_up: true
#   external_token_usage: false
#   weight_lineage: "qwen3"
#   role_uses_llama: {}
# leftover_llama_installs may list unused local tags only

scout roster
scout models
scout-mesh-status   # if using Tailscale split
```

### 5.2 Single-model paths

```bash
scout chat -m manager -p "Reply with exactly: PROMPT_OK" -v
scout dev --task-mode DEBUG -p "Reply with exactly: MODE_DEBUG_OK" -v
```

### 5.3 Full multi-agent crew

```bash
# defaults (AZ alpha built-ins)
scout crew -v
# or:
.venv/bin/python -m scout_crew.main
```

**Pass criteria**

| Check | Expected |
|-------|----------|
| Exit code | `0` |
| Roster | all roles on `scout-*` / `qwen3:8b` / hermes-hc — **no** `llama*` |
| Logs | no `llama3.1` model selection; no cloud hosts |
| Pipeline | real `ALERT:…`, intel JSON, `VET_PASS`/`VET_FAIL`, rank JSON, `nav_line` |
| Alpha | `phase_class: alpha_development`, AZ active, phase lock held |
| Artifacts | `output/local_brief.json`, `output/dev_brief.md` |

Last Qwen mesh verification snapshot:

- `output/verification/crew_qwen_run/summary.json` → **PASS** (`crew_exit: 0`)
- `output/verification/crew_qwen_run/llama_scan.txt` → no Llama hits in crew log / briefs
- `output/verification/crew_qwen_run/crew_run.log` → full sequential run

### 5.4 GUI

```bash
scout-gui
```

Tabs include Hermes, Crew, Chat, Blackboard, Pipeline, Terminal. Badge should show local/mesh Ollama up without cloud tokens.

---

## 6. Day-2 operations

| Task | Command |
|------|---------|
| Mesh health | `scout-mesh-status` |
| Rebuild specialists | `bash ~/Desktop/llm/build/build_llm_set.sh` |
| Rebuild hermes-hc | `bash ~/Desktop/llm/unified/build_hermes_hc.sh` |
| Drop leftover Llama tag | `ollama rm llama3.1` |
| Reset CrewAI memories | `crewai reset-memories -a` |
| Update deps | `uv lock && uv sync` |

---

## 7. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Ollama is unreachable` | start `ollama serve`; mesh: bind `0.0.0.0`, check Tailscale + firewall |
| Empty LLM / vet fails | rebuild specialists after Modelfile token bump; ensure crew `max_tokens` headroom for Qwen3 |
| Manager on wrong host | set `OLLAMA_HOST_MANAGER` / `SCOUT_PEER_OLLAMA_OPENAI` |
| `role_uses_llama` non-empty | fix `.env` pins; remove Llama from `OLLAMA_MODEL_*` |
| `leftover_llama_installs` only | safe; optional `ollama rm llama3.1` |
| Cloud key refused | unset provider keys; restore `.env` from example |
| Missing scout tags | `build_llm_set.sh` + `ollama list` |

---

## 8. Related docs

- [README.md](README.md) — overview + quick start
- [USAGE.md](USAGE.md) — CLI/GUI reference
- [AGENTS.md](AGENTS.md) — assistant reference
- [NOTICE](NOTICE) / [LICENSES/README.md](LICENSES/README.md) — Apache-2.0 vs Qwen weights
- `~/Desktop/llm/NOTICE` — Modelfile tree license notes
- `output/verification/` — smoke/integration summaries

---

## 9. Security notes

- Never commit `.env`.
- Trace links can expose prompts/tool I/O — treat as sensitive.
- Dummy `OPENAI_API_KEY=ollama` is intentional for local OpenAI-compatible clients.
- Tailscale peers are allowed; public cloud LLM endpoints are not.
