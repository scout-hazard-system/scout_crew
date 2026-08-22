# Verification snapshots

Committed summaries from local-only smoke tests. Replay crew integration with:

```bash
scout crew -v --inputs output/verification/crew_integration/inputs.json
```

See [SETUP.md](../../SETUP.md) and [USAGE.md](../../USAGE.md).

```json
{
  "title": "Scout Crew verification snapshots",
  "phase": "alpha_arizona_jurisdiction",
  "local_only": true,
  "suites": {
    "crew_integration": {
      "result": "PASS",
      "elapsed_s": 54.0,
      "notes": "Full sequential multi-agent crew; CREW_INTEGRATION_OK; 23 AZ marker filters"
    },
    "dev_mode_suite": {
      "result": "PASS",
      "modes": [
        "DEBUG",
        "PROCESS",
        "REVIEW",
        "IMPLEMENT",
        "TEST",
        "DOCS",
        "REFACTOR"
      ],
      "notes": "scout-dev path with prompt_syntax v1 envelope per mode"
    },
    "prompt_e2e": {
      "result": "PASS",
      "notes": "Idempotent PROMPT SYNTAX v1 conversion across CLI/GUI/crew paths"
    }
  }
}
```
