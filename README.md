# Scout Crew

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
| **[SETUP.md](SETUP.md)** | Full install process, models, verify steps |
| **[USAGE.md](USAGE.md)** | CLI/GUI reference, inputs/outputs, troubleshooting |
| **[AGENTS.md](AGENTS.md)** | CrewAI patterns for coding assistants |

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| Python | `>=3.10,<3.14` |
| [uv](https://docs.astral.sh/uv/) | package/tool runner |
| CrewAI CLI | `uv tool install crewai` |
| Ollama | `ollama serve` on `127.0.0.1:11434` |
| Scout models | see roster below |

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

```bash
ollama create scout-dev -f ~/Desktop/llm/dev/Modelfile.scout-dev
# or: bash ~/Desktop/llm/build/build_llm_set.sh
```

---

## Install (short)

Full detail: **[SETUP.md](SETUP.md)**.

```bash
cd ~/Desktop/scout_crew
cp -n .env.example .env
crewai install
ln -sfn "$(pwd)/bin/scout" ~/.local/bin/scout
ln -sfn "$(pwd)/bin/scout-gui" ~/.local/bin/scout-gui
scout status    # ollama_up true, external_token_usage false
```

Desktop launcher: `~/Desktop/Scout-Crew.desktop` (Allow Launching if blocked).

---

## Quick start

```bash
scout status && scout roster

# One-shot local chat (PROMPT SYNTAX v1 applied automatically)
scout chat -m manager -p "Reply with PROMPT_OK" -v
scout dev --task-mode DEBUG -p "Ping scout-dev"

# Full multi-agent pipeline (AZ alpha defaults)
scout crew -v

# Desktop GUI
scout-gui

# Route other OpenAI-compatible tools to Ollama
eval "$(scout env)"
```

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
| `output/verification/` | committed smoke/integration summaries |

Runtime `output/*` is gitignored except `.gitkeep` and `output/verification/**`.

---

## Architecture (short)

- **Process:** sequential (not hierarchical) — avoids manager re-query loops  
- **Admins:** `local_manager`, `dev_specialist` — no mutual approval; delegation off (prevents tool-JSON loops on local llama)  
- **Specialists:** no delegation; tight `max_iter`  
- **Guards:** `assert_local_only()`, acyclic task DAG, `planning=False`, `memory=False`  
- **Key modules:** `local_llms.py`, `admin_policy.py`, `prompt_syntax.py`, `arizona_phase.py`, `crew.py`, `cli.py`, `gui.py`

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
