# Crew verification — Qwen3 configuration

**License:** Apache-2.0 project source. Runtime weights: Qwen3 lineage (see root `NOTICE`).

## What was verified

- Sequential Scout crew (`python -m scout_crew.main` / `scout crew`)
- Role endpoints: specialists on local Ollama; manager/hermes on Windows Tailscale peer when configured
- No crew role resolved to a Llama tag
- Pipeline produced alert / intel / vet / rank / core / manager artifacts

## Files

| File | Purpose |
|------|---------|
| `summary.json` | Machine-readable pass/fail |
| `crew_run.log` | Full crew stdout/stderr |
| `llama_scan.txt` | Grep for llama/Meta in log + briefs |
| `specialist_smoke.log` | Direct specialist probes (if present) |

## Re-run

```bash
cd ~/Desktop/scout_crew
set -a && source .env && set +a
.venv/bin/python -m scout_crew.main
# then:
rg -ni 'llama' output/verification/crew_qwen_run/crew_run.log output/local_brief.json output/dev_brief.md
```

See [SETUP.md](../../../SETUP.md) §5.
