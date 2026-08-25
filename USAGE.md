# Scout Crew — Usage Guide

**License:** Apache License, Version 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

This document covers day-to-day operation of the local Scout CrewAI stack: CLI, GUI, inputs/outputs, models, and troubleshooting.

---

## 1. First-time setup

```bash
# Tools
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"   # if needed
uv tool install crewai

# Ollama must be running
ollama serve   # if not already a service
ollama list    # confirm scout-* and qwen3:8b

# Project
cd ~/Desktop/scout_crew
cp -n .env.example .env
crewai install

# PATH (once)
ln -sfn "$HOME/Desktop/scout_crew/bin/scout" "$HOME/.local/bin/scout"
ln -sfn "$HOME/Desktop/scout_crew/bin/scout-gui" "$HOME/.local/bin/scout-gui"
```

Verify:

```bash
scout status
# expect: ollama_up true, external_token_usage false
```

---

## 2. Environment variables

Copy from `.env.example`. Important keys:

| Variable | Purpose |
|----------|---------|
| `OLLAMA_BASE_URL` | Native Ollama HTTP API (`http://127.0.0.1:11434`) |
| `OPENAI_BASE_URL` / `OPENAI_API_BASE` | OpenAI-compatible endpoint (`.../v1`) |
| `OPENAI_API_KEY` | Dummy `ollama` (required by some clients) |
| `OLLAMA_MODEL_*` | Per-role overrides (`MANAGER`, `CORE`, `VET`, `ALERT`, `INTEL`, `RANK`, `DEV`, `BASE`) |
| `CREWAI_DISABLE_TELEMETRY` | Prefer `true` for quieter local runs |
| `CREWAI_TRACING_ENABLED` | `true` enables free local run traces |

**Do not** set cloud keys (`ANTHROPIC_API_KEY`, real OpenAI keys with api.openai.com base URL, etc.) if you want hard local-only mode — startup will refuse.

Apply routing in any shell:

```bash
eval "$(scout env)"
```

---

## 3. CLI reference (`scout`)

Binary: `bin/scout` → `python -m scout_crew.cli` inside the project venv.

### `scout status`

JSON diagnostics: Ollama reachability, installed models, role assignments, `external_token_usage`.

### `scout roster`

Compact `role → model` map.

### `scout models`

One installed model name per line (without `:latest` duplicates when possible).

### `scout env`

Prints `export ...` lines for OpenAI-compatible local routing. Use with `eval "$(scout env)"`.

### `scout chat`

One-shot completion through a role or raw Ollama model.

```bash
scout chat -m dev -p "Your prompt"
scout chat -m alert -p "Transcript: ..."
scout chat -m qwen3:8b -p "Hello"          # raw model name
echo "piped prompt" | scout chat -m core
scout chat -m dev -f ./notes.txt -p "Summarize the file"
scout chat -m manager -p "..." -v          # verbose route metadata on stderr
```

Flags:

| Flag | Default | Meaning |
|------|---------|---------|
| `-p/--prompt` | | Prompt text |
| `-f/--file` | | Extra prompt body from file |
| `-m/--model` | `dev` | Role alias or Ollama model |
| `--system` | built-in | System preamble |
| `--temperature` | `0.2` | Sampling |
| `--max-tokens` | `2048` | Cap |
| `-v/--verbose` | off | Print route JSON on stderr |

Role aliases: `dev`, `manager`/`mgr`/`admin`, `core`/`nav`/`chat`, `alert`, `intel`, `vet`, `rank`, `base`/`llama`/`qwen3:8b`.

### Prompt syntax v1

All `chat` / `dev` prompts are wrapped by `build_chat_messages()` in `prompt_syntax.py`:

```
=== PROMPT SYNTAX v1 ===
role: <role>
...
=== USER QUERY (ADMIN-PRIVILEGED) ===
privilege: admin
priority: 1
<source optional>
<raw user text>
=== END USER QUERY ===
=== TASK MODE ===          # optional
=== TASK CONTEXT ===       # optional
=== USER QUERY REMINDER ===
```

Idempotent: raw text, legacy `=== ADMIN-PRIVILEGED USER PROMPT ===` banners, and already-v1 envelopes are peeled then re-wrapped once.

Useful flags:

| Flag | Meaning |
|------|---------|
| `--task-mode` | DEBUG / PROCESS / REVIEW / IMPLEMENT / TEST / DOCS / REFACTOR / ADMIN_USER_PROMPT |
| `--task-context` | inline retained context |
| `--task-context-file` | file retained as TASK CONTEXT |
| `-f/--file` | preferred for multi-line GUI prompts |

Verbose stderr includes `"prompt_syntax": "v1"` and `"envelope": true`.

### `scout dev`

Same as `scout chat -m dev` with an admin/debug system preamble. No manager approval required for this path (direct model call).

### `scout crew`

Runs the full sequential multi-agent crew.

```bash
scout crew -v
scout crew --inputs ./my_inputs.json
scout crew --transcript "Unit 1 radar on I-5..." --dev-mode DEBUG --dev-request "Explain vet failure modes"
scout crew --keep-cwd    # do not chdir to project root
```

Flags:

| Flag | Meaning |
|------|---------|
| `--inputs PATH` | JSON object merged into default inputs |
| `--transcript` | Override transcript |
| `--dev-mode` | `PROCESS` / `REVIEW` / `DEBUG` / … |
| `--dev-request` | Instructions for scout-dev admin task |
| `-p` / `--prompt` / `--user-prompt` | Operator prompt (converted to PROMPT SYNTAX v1) |
| `--keep-cwd` | Stay in caller cwd (outputs may land elsewhere) |
| `-v/--verbose` | Print roster on stderr before kickoff |

Also available via CrewAI:

```bash
cd ~/Desktop/scout_crew
crewai run
```

---

## 4. Inputs JSON schema

Defaults are defined in `src/scout_crew/main.py`. Override any subset:

```json
{
  "transcript": "Unit 12 Phoenix PD, traffic stop on I-10 eastbound near 7th Ave...",
  "route_context": "origin 33.4484,-112.0740; jurisdiction=AZ; waze_hazards=ok",
  "location_context": {
    "city": "Phoenix",
    "state": "AZ",
    "phase_class": "alpha_development",
    "deployment_phase": 1
  },
  "channel_candidates": [
    {"id": "a", "name": "Phoenix Police", "state": "AZ"},
    {"id": "b", "name": "Arizona DPS", "state": "AZ"}
  ],
  "dev_mode": "PROCESS",
  "dev_request": "Confirm AZ-only scope and marker filters.",
  "user_prompt": "Answer first, then finish the brief.",
  "user_prompt_raw": "Answer first, then finish the brief.",
  "user_prompt_privilege": "admin"
}
```

Objects/arrays in the file are JSON-encoded automatically when loaded.

GUI writes `output/gui_inputs.json` before each GUI-triggered crew run.

---

## 5. Outputs

| Path | Description |
|------|-------------|
| `output/local_brief.json` | Manager final synthesis (when written) |
| `output/dev_brief.md` | scout-dev admin brief |
| `output/az_manager_status.json` | AZ jurisdiction / marker filter status |
| `output/gui_inputs.json` | Last GUI crew inputs (includes v1 `user_prompt`) |
| `output/gui_chat_prompt.txt` | Raw main-window chat prompt (CLI envelopes) |
| `output/gui_dev_prompt.txt` | Raw Dev Conversations prompt |
| `output/verification/` | Committed smoke + integration summaries |

Runtime `output/*` is gitignored except `.gitkeep` and `output/verification/**`.

---

## 6. Desktop GUI (`scout-gui`)

```bash
scout-gui
```

### Layout

**Left**
- Local models / routing status (auto-refresh ~15s)
- CrewAI pipeline: manager user prompt, transcript, dev mode, dev request, Run / Stop
- Direct chat: **manager** and **core** only (+ read-only response panel)
- Button to open **Dev Conversations** (scout-dev, task modes DEBUG…REFACTOR)

**Right tabs**
- **Crew output** — live stdout/stderr from `scout crew`
- **Chat output** — live stdout/stderr from `scout chat`
- **Terminal** — bash session with forced local Ollama env (`OPENAI_BASE_URL=http://127.0.0.1:11434/v1`)

### Typical GUI flow

1. Confirm green badge: `LOCAL · Ollama up · no cloud tokens`
2. Edit transcript / dev request if needed
3. Click **Run full crew**
4. Watch **Crew output** tab
5. When finished, open `output/` or use **Open output folder**
6. Optional: use **Send chat** for quick single-model checks
7. Optional: **Terminal** tab for `ollama list`, `scout status`, etc.

### Desktop entry notes (Pop!_OS / COSMIC)

- File: `~/Desktop/Scout-Crew.desktop`
- If double-click opens an editor, right-click → **Allow Launching**, or run `scout-gui` from a terminal
- Icon: `assets/scout.png`

---

## 7. Admin roles and anti-recursion

| Agent | Level | Delegation | max_iter |
|-------|--------|------------|----------|
| `local_manager` | admin | **disabled** (avoids tool-JSON loops) | 10 |
| `dev_specialist` (`scout-dev`) | admin | **disabled** | 10 |
| alert / intel / vet / rank / core | specialist | **disabled** | 4 |

Rules enforced in code + prompts (`admin_policy.py`):

- Sequential process (no hierarchical manager planner loop)
- Acyclic task `context:` DAG validated at crew build
- `planning=False`, `memory=False`
- Admins complete their own tasks without mutual approval
- Specialists never delegate
- No “ask agent X again / loop until” style self-recursion in prompts

---

## 8. Project layout

```
scout_crew/
├── .env.example
├── README.md
├── SETUP.md                 ← full install process
├── USAGE.md                 ← this file
├── AGENTS.md                ← CrewAI assistant reference
├── pyproject.toml
├── uv.lock
├── bin/
│   ├── scout
│   └── scout-gui
├── assets/scout.png
├── knowledge/
├── output/
│   ├── .gitkeep
│   └── verification/        ← committed smoke/integration summaries
├── src/scout_crew/
│   ├── admin_policy.py
│   ├── arizona_phase.py
│   ├── prompt_syntax.py
│   ├── cli.py
│   ├── crew.py
│   ├── gui.py
│   ├── local_llms.py
│   ├── main.py
│   └── config/
│       ├── agents.yaml
│       ├── tasks.yaml
│       └── arizona_phase.json
└── tests/
```

Sibling (not in this git repo): `~/Desktop/llm/` Modelfiles and `build_llm_set.sh`.

---

## 9. Troubleshooting

| Symptom | What to try |
|---------|-------------|
| `Ollama is unreachable` | `ollama serve`; `curl -s http://127.0.0.1:11434/api/tags` |
| Wrong / missing model | `ollama list`; rebuild with Modelfile; check `OLLAMA_MODEL_*` in `.env` |
| Cloud key refused | Unset provider keys; restore `.env` from `.env.example` |
| `scout: missing venv` | `cd ~/Desktop/scout_crew && crewai install` |
| GUI won’t start | Ensure `DISPLAY` set; run `scout-gui` from terminal; check `/tmp/scout-gui.log` |
| Desktop file opens in editor | Allow Launching, or use `scout-gui` |
| Crew slow | Normal on CPU; first load pulls model into memory |
| Manager JSON looks tool-shaped | Known formatting quirk with some local models; specialists still ran — tighten manager prompt/task if needed |
| Nested git confusion | This project is `~/Desktop/scout_crew` (its own repo), not the parent Desktop repo |

Debug one model:

```bash
scout chat -m dev -p "ping" -v
# stderr should show base_url http://127.0.0.1:11434/v1 and external_token_usage false
```

---

## 10. Development notes

- Prefer small diffs; bump scout model **third** version digit when changing core models in the sibling llm tree (project convention).
- After dependency changes: `uv lock` / `crewai install`.
- Do not commit `.env` or raw runtime `output/*` (except `output/verification/**` summaries).
- See SETUP.md for first-time install and verification commands.

---

## 11. Verification artifacts

Committed under `output/verification/` after local smoke tests:

| Path | What it proves |
|------|----------------|
| `crew_integration/validation.json` | Full multi-agent crew PASS (AZ alpha, prompt v1) |
| `crew_integration/inputs.json` | Replay inputs for `scout crew --inputs ...` |
| `crew_integration/parsed_brief.json` | Manager brief fields from integration run |
| `dev_mode_suite/summary.json` | scout-dev modes DEBUG…REFACTOR all PASS |
| `prompt_e2e/crew_path_check.json` | Idempotent envelope path checks |

Large logs (`crew.stdout`, per-mode `.out`) stay local/gitignored.

- Co-author agent commits with: `Co-Authored-By: Warp <agent@warp.dev>` when applicable.
