# Scout Crew

Local-only [CrewAI](https://crewai.com) multi-agent system for on-device **scout** models served by [Ollama](https://ollama.com).

**Design goals**
- Zero cloud LLM token usage (OpenAI-compatible traffic forced to `127.0.0.1:11434`)
- Role-specialized scout models + admin manager / scout-dev
- Sequential pipeline with anti-recursion guards
- CLI + desktop GUI with integrated terminal

> Related model sources live outside this repo under `~/Desktop/llm/` (Modelfiles, build scripts).

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

Build / refresh scout-dev (from sibling llm tree):

```bash
ollama create scout-dev -f ~/Desktop/llm/dev/Modelfile.scout-dev
# or full set:
bash ~/Desktop/llm/build/build_llm_set.sh
```

---

## Install

```bash
cd ~/Desktop/scout_crew
cp .env.example .env          # already local-only defaults
crewai install                # creates .venv + installs deps
# optional PATH shims (if not already linked):
ln -sfn "$(pwd)/bin/scout" ~/.local/bin/scout
ln -sfn "$(pwd)/bin/scout-gui" ~/.local/bin/scout-gui
```

Desktop launcher (Pop!_OS / COSMIC):

- `~/Desktop/Scout-Crew.desktop`
- `~/.local/share/applications/scout-crew.desktop`

If the desktop icon is blocked, right-click → **Allow Launching**, or run `scout-gui`.

---

## Quick start

```bash
# Health
scout status
scout roster
scout models

# One-shot local chat (admin dev model)
scout chat -m dev -p "Reply with LOCAL_OK"
scout dev -p "TASK: PROCESS\nGive a 5-step Ollama health checklist"

# Full multi-agent pipeline
scout crew -v

# Desktop GUI
scout-gui
```

Point other OpenAI-compatible tools at local Ollama:

```bash
eval "$(scout env)"
```

---

## Usage

See **[USAGE.md](USAGE.md)** for full CLI flags, GUI walkthrough, inputs JSON schema, outputs, troubleshooting, and architecture.

### CLI cheat sheet

| Command | Purpose |
|---------|---------|
| `scout status` | Ollama up? role map? cloud usage flag |
| `scout roster` | role → model |
| `scout models` | installed tags |
| `scout env` | shell exports for local routing |
| `scout chat -m ROLE -p "..."` | single local completion |
| `scout dev -p "..."` | admin shortcut → `scout-dev` |
| `scout crew [-v] [--inputs file.json]` | full sequential crew |
| `scout-gui` | desktop control plane + terminal |
| `crewai run` | CrewAI project entry (same crew) |

### Pipeline order

1. `alert_task` → scout-alert  
2. `intel_task` → scout-intel  
3. `vet_task` → scout-vet (uses alert context)  
4. `rank_task` → scout-rank  
5. `core_task` → scout-core  
6. `dev_task` → scout-dev **(admin, no manager approval)**  
7. `manager_synthesis_task` → llama3.1 **(admin final brief)**  

### Outputs

| File | Producer |
|------|----------|
| `output/local_brief.json` | manager synthesis |
| `output/dev_brief.md` | scout-dev |
| `output/gui_inputs.json` | written by GUI when you run crew |

---

## Architecture (short)

- **Process:** sequential (not hierarchical) to avoid manager re-query loops  
- **Admins:** `local_manager`, `dev_specialist` — optional one-hop consult; never admin↔admin delegation  
- **Specialists:** no delegation; low `max_iter`  
- **Guards:** `assert_local_only()`, acyclic task context DAG, `planning=False`, `memory=False`  
- **Key modules:**  
  - `src/scout_crew/local_llms.py` — Ollama roster / LLM factory  
  - `src/scout_crew/admin_policy.py` — admin partition + anti-recursion  
  - `src/scout_crew/crew.py` — CrewAI wiring  
  - `src/scout_crew/cli.py` — `scout` CLI  
  - `src/scout_crew/gui.py` — desktop GUI  

---

## Safety / local-only

- `.env` must keep `OPENAI_BASE_URL` / `OPENAI_API_BASE` on `127.0.0.1:11434`  
- Dummy key `OPENAI_API_KEY=ollama` is intentional for OpenAI-compatible clients  
- `assert_local_only()` refuses common cloud provider env keys  
- Do not commit real API keys (`.env` is gitignored)

---

## License / notes

Project scaffold originated from CrewAI classic template; Scout-specific agents, local routing, CLI, and GUI are project code. CrewAI remains subject to its own license.
