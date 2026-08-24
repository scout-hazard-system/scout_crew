# Scout Crew

**License:** Apache License, Version 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

Local-only [CrewAI](https://crewai.com) multi-agent system for on-device **scout** models served by [Ollama](https://ollama.com).

**Design goals**
- Zero cloud LLM token usage (OpenAI-compatible traffic forced to `127.0.0.1:11434`)
- Role-specialized scout models + admin manager / scout-dev
- Sequential pipeline with anti-recursion guards
- PROMPT SYNTAX v1 envelopes for every user prompt (CLI + GUI + crew)
- Arizona **alpha** jurisdiction lock (all facets on, non-AZ out of scope)
- CLI + desktop GUI (admin/core chat + Dev Conversations window)

> Related model sources live outside this repo under `~/Desktop/llm/` (Modelfiles, build scripts).

---

## Docs map

| Doc | Contents |
|-----|----------|
| **This README** | Setup + verification checklist (start here) |
| **[SETUP.md](SETUP.md)** | Expanded install, architecture, day-2 ops |
| **[USAGE.md](USAGE.md)** | Full CLI/GUI reference, inputs/outputs, troubleshooting |
| **[AGENTS.md](AGENTS.md)** | CrewAI patterns for coding assistants |
| **[output/verification/](output/verification/)** | Committed smoke/integration summaries |

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| Python | `>=3.10,<3.14` |
| [uv](https://docs.astral.sh/uv/) | package / tool runner |
| CrewAI CLI | `uv tool install crewai` (optional global; project uses its own venv) |
| Ollama | listening on `127.0.0.1:11434` |
| Scout models | roster below |

### Install host tools

```bash
# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"   # if needed

# CrewAI CLI (optional)
uv tool install crewai

# Ollama must be running
ollama serve    # if not already a service
curl -s http://127.0.0.1:11434/api/tags | head
```

### Recommended Ollama models

| Role | Model tag |
|------|-----------|
| Manager (admin) | `llama3.1` |
| Dev (admin) | `scout-dev` |
| Core / nav / chat | `scout-core1.0.5` |
| Alert | `scout-alert` |
| Intel | `scout-intel` |
| Vet | `scout-vet1.0.6` |
| Rank | `scout-rank` |
| Fallback | `llama3.1` |

Build / refresh from the sibling llm tree:

```bash
ollama create scout-dev -f ~/Desktop/llm/dev/Modelfile.scout-dev
# or full set:
bash ~/Desktop/llm/build/build_llm_set.sh
ollama list | egrep 'scout-|llama3.1'
```

---

## Setup

### 1. Clone and install the project

```bash
cd ~/Desktop/scout_crew          # or: git clone https://github.com/wendigoro/scout_crew.git
cp -n .env.example .env
crewai install                   # creates .venv + installs deps (CrewAI, PySide6, …)

mkdir -p ~/.local/bin
ln -sfn "$(pwd)/bin/scout" ~/.local/bin/scout
ln -sfn "$(pwd)/bin/scout-gui" ~/.local/bin/scout-gui
hash -r
```

### 2. Local-only environment

`.env` must keep traffic on loopback (see `.env.example`):

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

- Do **not** point `OPENAI_BASE_URL` at cloud hosts.
- Dummy key `OPENAI_API_KEY=ollama` is intentional for OpenAI-compatible clients.
- `assert_local_only()` refuses common cloud provider env keys.

Route other OpenAI-compatible tools to Ollama:

```bash
eval "$(scout env)"
```

### 3. Desktop launcher (optional)

- `~/Desktop/Scout-Crew.desktop`
- `~/.local/share/applications/scout-crew.desktop`

If the icon is blocked: right-click → **Allow Launching**, or run `scout-gui`.

### 4. What setup installs

```
User / GUI / CLI
      │
      ▼
PROMPT SYNTAX v1  (ADMIN-PRIVILEGED USER QUERY)
      │
      ├─ scout chat | scout dev  → single local role model
      │
      └─ scout crew (sequential)
            alert → intel → vet → rank → core
            → dev (admin) → manager synthesis (admin)
```

| Concern | Module / behavior |
|---------|-------------------|
| Local-only LLMs | `local_llms.py`, CLI/GUI env hard-pin |
| Anti-recursion | sequential process, `planning=False`, `memory=False`, DAG check |
| Admin user prompts | `prompt_syntax.py`, `admin_policy.py` |
| AZ alpha scope | `arizona_phase.py`, `config/arizona_phase.json` |
| Traces | `CREWAI_TRACING_ENABLED=true` (models still local) |

More detail: [SETUP.md](SETUP.md).

---

## Verification

Run these in order after setup. All LLM calls must stay on `127.0.0.1:11434`.

### Step A — Health and roster

```bash
scout status
# expect: "ollama_up": true, "external_token_usage": false

scout roster
# expect role → model map (manager/llama3.1, dev/scout-dev, …)

scout models
# expect scout-* and llama3.1 tags
```

### Step B — Single-model chat (prompt syntax v1)

```bash
scout chat -m manager -p "Reply with exactly: PROMPT_OK" -v
```

**Pass criteria**
- stdout contains `PROMPT_OK` (or a clear manager answer)
- stderr JSON includes `"prompt_syntax": "v1"`, `"envelope": true`
- `"base_url"` is `http://127.0.0.1:11434/v1`
- `"external_token_usage": false`

### Step C — scout-dev task mode (GUI Dev path)

```bash
scout dev --task-mode DEBUG -p "Reply with exactly: MODE_DEBUG_OK" -v
```

**Pass criteria**
- exit code 0, non-empty reply
- stderr: `"role": "dev"`, `"task_mode": "DEBUG"`, `"prompt_syntax": "v1"`

Optional full mode matrix (DEBUG → REFACTOR): see committed summary  
`output/verification/dev_mode_suite/summary.json` (7/7 PASS on last smoke).

### Step D — Full multi-agent crew (sample task)

**Option 1 — committed integration inputs (recommended replay)**

```bash
scout crew -v --inputs output/verification/crew_integration/inputs.json
```

**Option 2 — defaults (AZ alpha built-ins)**

```bash
scout crew -v
```

**Option 3 — ad-hoc sample inputs**

```bash
mkdir -p output/sample_verify
cat > output/sample_verify/inputs.json <<'EOF'
{
  "transcript": "Unit 7 Phoenix PD, vehicle stop on US-60 eastbound near Rural Rd, radar check complete, subject cooperative.",
  "dev_mode": "PROCESS",
  "dev_request": "Sample verify: one-line note that AZ alpha scope is held.",
  "user_prompt": "Sample task: reply first with SAMPLE_CREW_OK, confirm alpha_development and AZ active, then finish the brief.",
  "user_prompt_raw": "Sample task: reply first with SAMPLE_CREW_OK, confirm alpha_development and AZ active, then finish the brief.",
  "user_prompt_privilege": "admin"
}
EOF
scout crew -v --inputs output/sample_verify/inputs.json
```

**Pass criteria (manager final brief)**

| Check | Expected |
|-------|----------|
| Exit code | `0` |
| Local roster on stderr | includes `scout-dev`, `llama3.1`, other scout tags |
| No cloud host | no `api.openai.com` in logs |
| User prompt honored | e.g. `SAMPLE_CREW_OK` / `CREW_INTEGRATION_OK` in `user_response` |
| Admin priority | `user_priority_applied: true`, `user_prompt_admin_privilege: true` |
| Task context | `task_context_retained: true` |
| Alpha lock | `phase_class: alpha_development`, `deployment_phase: 1`, `phase_lock_held: true` |
| AZ scope | `az_manager_status: AZ_JURISDICTION_ACTIVE`, `az_shard: AZ` |
| Marker filters | non-empty `az_location_marker_filters` (typically ~23) |
| Pipeline | real `ALERT:…` (not template), `VET_PASS`/`VET_FAIL`, `nav_line` set |
| Artifacts | `output/az_manager_status.json`, `output/dev_brief.md` written |

Last committed integration snapshot:  
`output/verification/crew_integration/validation.json` → **PASS** (~54s local run).

### Step E — GUI smoke (optional)

```bash
scout-gui
```

1. Badge: `LOCAL · Ollama up · no cloud tokens`
2. Main chat limited to **manager** / **core**
3. Open **Dev Conversations** → send a DEBUG message
4. Confirm read-only response panel updates
5. **Run full crew** → live Crew tab + `output/gui_inputs.json`

---

## Quick start (after verification)

```bash
scout status && scout roster
scout chat -m manager -p "Reply with PROMPT_OK" -v
scout dev --task-mode DEBUG -p "Ping scout-dev"
scout crew -v
scout-gui
eval "$(scout env)"
```

### CLI cheat sheet

| Command | Purpose |
|---------|---------|
| `scout status` | Ollama up? role map? cloud usage flag |
| `scout roster` | role → model |
| `scout models` | installed tags |
| `scout env` | shell exports for local routing |
| `scout chat -m ROLE -p "…"` | single local completion (v1 envelope) |
| `scout dev -p "…"` | admin shortcut → `scout-dev` |
| `scout crew [-v] [--inputs file.json]` | full sequential crew |
| `scout-gui` | desktop control plane + terminal |
| `crewai run` | CrewAI project entry (same crew) |

---

## Pipeline order

1. `alert_task` → scout-alert  
2. `intel_task` → scout-intel  
3. `vet_task` → scout-vet  
4. `rank_task` → scout-rank  
5. `core_task` → scout-core  
6. `dev_task` → scout-dev **(admin)**  
7. `manager_synthesis_task` → llama3.1 **(admin final brief)**  

User prompts are **admin-privileged**: answer first, retain task context, finish deliverable (no drop-through).

---

## Prompt syntax v1

Every chat/dev/crew user prompt is converted to a canonical envelope:

- `=== PROMPT SYNTAX v1 ===`
- `=== USER QUERY (ADMIN-PRIVILEGED) ===` … `=== END USER QUERY ===`
- optional `TASK MODE` / `TASK CONTEXT`
- trailing reminder for small local models

Conversion is **idempotent** (raw, legacy admin banner, or already-v1 input peels cleanly). GUI writes raw text to `output/gui_*_prompt.txt`; CLI applies the envelope once.

---

## Alpha phase (Arizona)

Until an explicit **second deployment phase** prompt:

- `phase_class=alpha_development`, `deployment_phase=1`
- All pipelines/catalogs scoped to **AZ only**
- Scanner/hazard/ranking **essential inside AZ**
- Location marker filters set on the AZ shard

Module: `src/scout_crew/arizona_phase.py`.

---

## Outputs

| Path | Producer |
|------|----------|
| `output/local_brief.json` | manager synthesis (when written) |
| `output/dev_brief.md` | scout-dev |
| `output/az_manager_status.json` | AZ scope apply status |
| `output/gui_inputs.json` | GUI crew run |
| `output/gui_*_prompt.txt` | raw GUI prompts (CLI envelopes them) |
| `output/verification/` | committed smoke/integration summaries |

Runtime `output/*` is gitignored except `.gitkeep` and `output/verification/**`.

### Verification artifacts (committed)

| Path | Proves |
|------|--------|
| `output/verification/index.json` | suite index |
| `output/verification/crew_integration/validation.json` | full multi-agent crew PASS |
| `output/verification/crew_integration/inputs.json` | replay inputs for `scout crew` |
| `output/verification/dev_mode_suite/summary.json` | scout-dev modes DEBUG…REFACTOR |
| `output/verification/prompt_e2e/crew_path_check.json` | idempotent prompt envelope paths |

---

## Architecture (short)

- **Process:** sequential (not hierarchical) — avoids manager re-query loops  
- **Admins:** `local_manager`, `dev_specialist` — no mutual approval; delegation off (prevents tool-JSON loops on local llama)  
- **Specialists:** no delegation; tight `max_iter`  
- **Guards:** `assert_local_only()`, acyclic task DAG, `planning=False`, `memory=False`  
- **Key modules:** `local_llms.py`, `admin_policy.py`, `prompt_syntax.py`, `arizona_phase.py`, `crew.py`, `cli.py`, `gui.py`

---

## Troubleshooting (setup / verify)

| Symptom | Fix |
|---------|-----|
| `Ollama is unreachable` | `ollama serve`; `curl -s http://127.0.0.1:11434/api/tags` |
| Missing model tag | `ollama list`; rebuild Modelfile; check `OLLAMA_MODEL_*` in `.env` |
| Cloud key refused | unset provider keys; restore `.env` from `.env.example` |
| `scout: missing venv` | `cd ~/Desktop/scout_crew && crewai install` |
| Crew slow | normal on CPU; first call loads model weights |
| Manager tool-shaped JSON | admins have delegation disabled; use sequential `scout crew` only |
| GUI won’t start | run `scout-gui` from a desktop session; check `DISPLAY` |

More: [USAGE.md](USAGE.md) § Troubleshooting, [SETUP.md](SETUP.md) § Troubleshooting setup.

---

## Safety / local-only

- Keep `OPENAI_BASE_URL` / `OPENAI_API_BASE` on `127.0.0.1:11434`  
- Dummy key `OPENAI_API_KEY=ollama` is intentional  
- `assert_local_only()` refuses common cloud provider env keys  
- Do not commit real API keys (`.env` is gitignored)  
- Trace links may include prompts — treat as sensitive  

---

## License / notes

Project scaffold originated from CrewAI classic template; Scout-specific agents, local routing, CLI, GUI, AZ phase, and prompt syntax are project code. CrewAI remains subject to its own license.
