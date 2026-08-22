# Scout Crew — Setup Process

End-to-end setup for the **local-only** multi-agent Scout stack (CrewAI + Ollama).
No cloud LLM tokens: all OpenAI-compatible traffic is forced to `http://127.0.0.1:11434/v1`.

---

## 1. System prerequisites

| Tool | Why |
|------|-----|
| Linux desktop (Pop!_OS tested) | GUI + Ollama host |
| Python `>=3.10,<3.14` | CrewAI runtime |
| [uv](https://docs.astral.sh/uv/) | deps + CrewAI CLI install |
| [Ollama](https://ollama.com) | local model server on `:11434` |
| Git | clone / updates |

```bash
# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"   # if needed

# CrewAI CLI (optional global; project also uses its own venv)
uv tool install crewai

# Ollama
ollama serve    # if not already a systemd/user service
curl -s http://127.0.0.1:11434/api/tags | head
```

---

## 2. Local models (roster)

| Role | Ollama tag | Notes |
|------|------------|--------|
| Manager (admin) | `llama3.1` | synthesis + AZ alpha persona |
| Dev (admin) | `scout-dev` | process/debug; no manager approval |
| Core | `scout-core1.0.5` | nav/chat package |
| Alert | `scout-alert` | ALERT:/IGNORE |
| Intel | `scout-intel` | dispatch structure |
| Vet | `scout-vet1.0.6` | VET_PASS / VET_FAIL |
| Rank | `scout-rank` | channel ranking |
| Base fallback | `llama3.1` | generic |

Build / refresh from the sibling llm tree (outside this repo):

```bash
ollama create scout-dev -f ~/Desktop/llm/dev/Modelfile.scout-dev
# or full set:
bash ~/Desktop/llm/build/build_llm_set.sh
ollama list | egrep 'scout-|llama3.1'
```

---

## 3. Project install

```bash
cd ~/Desktop/scout_crew
cp -n .env.example .env
crewai install          # creates .venv, installs crewai + PySide6, etc.

# PATH launchers
mkdir -p ~/.local/bin
ln -sfn "$PWD/bin/scout" ~/.local/bin/scout
ln -sfn "$PWD/bin/scout-gui" ~/.local/bin/scout-gui
hash -r
```

### `.env` (local-only)

Critical values (see `.env.example`):

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11434
OPENAI_API_KEY=ollama
OPENAI_API_BASE=http://127.0.0.1:11434/v1
OPENAI_BASE_URL=http://127.0.0.1:11434/v1
OLLAMA_MODEL_MANAGER=ollama/llama3.1
OLLAMA_MODEL_CORE=ollama/scout-core1.0.5
OLLAMA_MODEL_VET=ollama/scout-vet1.0.6
OLLAMA_MODEL_ALERT=ollama/scout-alert
OLLAMA_MODEL_INTEL=ollama/scout-intel
OLLAMA_MODEL_RANK=ollama/scout-rank
OLLAMA_MODEL_DEV=ollama/scout-dev
CREWAI_TRACING_ENABLED=true
```

Do **not** point `OPENAI_BASE_URL` at cloud hosts. `assert_local_only()` refuses common cloud provider keys.

Optional shell routing for other tools:

```bash
eval "$(scout env)"
```

### Desktop launcher (optional)

- `~/Desktop/Scout-Crew.desktop`
- `~/.local/share/applications/scout-crew.desktop`

If the icon is blocked: right-click → **Allow Launching**, or run `scout-gui`.

---

## 4. Architecture (what you just installed)

```
User / GUI / CLI
      │
      ▼
prompt_syntax v1 envelope  (ADMIN-PRIVILEGED USER QUERY)
      │
      ├─ scout chat|dev  → single local role model
      │
      └─ scout crew (sequential, no hierarchical planner)
            1 alert → 2 intel → 3 vet → 4 rank → 5 core
            6 dev (admin) → 7 manager synthesis (admin)
```

| Concern | Implementation |
|---------|----------------|
| Local-only LLMs | `local_llms.py`, CLI/GUI env hard-pin |
| Anti-recursion | sequential process, `planning=False`, `memory=False`, DAG check, no admin↔admin delegation |
| Admin user prompts | `prompt_syntax.py` + `admin_policy.py` |
| Alpha AZ scope | `arizona_phase.py` + `config/arizona_phase.json` |
| Traces | `CREWAI_TRACING_ENABLED=true` (local models still) |

---

## 5. Verify install

```bash
scout status      # ollama_up true, external_token_usage false
scout roster
scout models

# Prompt syntax + single-model path
scout chat -m manager -p "Reply with exactly: PROMPT_OK" -v
# stderr JSON: prompt_syntax=v1, envelope=true, base_url ...11434/v1

# Dev window path (all task modes)
scout dev -f /dev/stdin --task-mode DEBUG -p "Reply MODE_DEBUG_OK" -v

# Full multi-agent integration
scout crew -v --inputs output/verification/crew_integration/inputs.json
# or defaults:
scout crew -v
```

Expected manager fields on a healthy AZ alpha run:

- `user_priority_applied: true`
- `phase_class: alpha_development`, `deployment_phase: 1`, `phase_lock_held: true`
- `az_manager_status: AZ_JURISDICTION_ACTIVE`
- non-empty `az_location_marker_filters`
- specialist-derived `alert` / `vet` / `nav_line`

---

## 6. GUI setup check

```bash
scout-gui
```

1. Badge: `LOCAL · Ollama up · no cloud tokens`
2. Main chat: **manager** / **core** only
3. **Dev Conversations** window: scout-dev + modes DEBUG…REFACTOR
4. Chat/dev prompts are written raw under `output/`; CLI applies PROMPT SYNTAX v1 once
5. Response panel is read-only (model/crew reply for current prompt)
6. **Run full crew** → `output/gui_inputs.json` + live Crew tab

---

## 7. Day-2 operations

| Task | Command |
|------|---------|
| Reset CrewAI memories | `crewai reset-memories -a` |
| Enable traces | already on via `.env`; or `crewai traces enable` |
| View last task outputs | `crewai log-tasks-outputs` |
| Update deps | `uv lock && crewai install` |
| Rebuild a scout model | `ollama create <tag> -f ~/Desktop/llm/...` |

---

## 8. Troubleshooting setup

| Symptom | Fix |
|---------|-----|
| `Ollama is unreachable` | start `ollama serve`; check firewall/port 11434 |
| Missing `scout-dev` | create from Modelfile; `scout roster` |
| `scout: missing venv` | `crewai install` in project root |
| Cloud key refused | unset provider keys; restore `.env` from example |
| GUI blank / no display | run from desktop session; check `DISPLAY` |
| Double-wrapped prompts | fixed by idempotent `convert_user_prompt`; GUI sends raw text |
| Manager emits tool JSON | delegation disabled on admins; use sequential crew only |

---

## 9. Related docs

- [README.md](README.md) — overview + quick start
- [USAGE.md](USAGE.md) — CLI/GUI reference, inputs, verification artifacts
- [AGENTS.md](AGENTS.md) — CrewAI coding assistant reference
- `output/verification/` — committed smoke/integration summaries (see USAGE)

---

## 10. Security notes

- Never commit `.env` (gitignored).
- Trace links can expose prompts/tool I/O — treat as sensitive.
- Dummy `OPENAI_API_KEY=ollama` is intentional for local OpenAI-compatible clients.
