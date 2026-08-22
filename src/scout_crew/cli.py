#!/usr/bin/env python
"""scout — local CLI routing all LLM tokens through Ollama / CrewAI.

No cloud provider calls. OpenAI-compatible traffic goes to
http://127.0.0.1:11434/v1 only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv

# Project root (.env lives here)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")

# Force local routing even if the parent shell exported cloud keys/URLs.
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY") or "ollama"
os.environ["OPENAI_API_BASE"] = os.getenv("OPENAI_API_BASE") or "http://127.0.0.1:11434/v1"
os.environ["OPENAI_BASE_URL"] = os.getenv("OPENAI_BASE_URL") or "http://127.0.0.1:11434/v1"
os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
os.environ["CREWAI_TRACING_ENABLED"] = os.getenv("CREWAI_TRACING_ENABLED", "true")

from scout_crew.arizona_phase import (  # noqa: E402
    apply_all_pipeline_scope,
    detect_phase_transition,
    manager_phase_prompt_block,
    manager_status_payload,
)
from scout_crew.local_llms import (  # noqa: E402
    assert_local_only,
    make_llm,
    model_roster,
    resolve_role_model,
    status,
)

from scout_crew.prompt_syntax import (  # noqa: E402
    ROLE_ALIASES,
    ROLE_SYSTEM_PROMPTS,
    build_chat_messages,
    convert_user_prompt,
    extract_raw_user_query,
    is_prompt_syntax_v1,
    normalize_role,
    system_for_role,
)


def _die(msg: str, code: int = 1) -> None:
    print(f"scout: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _read_stdin_if_piped() -> str:
    if sys.stdin.isatty():
        return ""
    return sys.stdin.read().strip()


def cmd_status(_: argparse.Namespace) -> int:
    assert_local_only()
    print(json.dumps(status(), indent=2))
    return 0


def cmd_roster(_: argparse.Namespace) -> int:
    assert_local_only()
    print(json.dumps(model_roster(), indent=2))
    return 0


def cmd_models(_: argparse.Namespace) -> int:
    assert_local_only()
    data = status()
    for name in data.get("installed_models") or []:
        if not str(name).endswith(":latest"):
            print(name)
    return 0


def _resolve_role_or_model(spec: str) -> tuple[str, str]:
    """Return (role_or_custom, model_name). role is role alias or bare model."""
    key = (spec or "dev").strip()
    lower = key.lower()
    if lower in ROLE_ALIASES:
        role = ROLE_ALIASES[lower]
        return role, resolve_role_model(role)
    # treat as explicit ollama model name
    bare = key[len("ollama/") :] if key.startswith("ollama/") else key
    return "custom", bare


def cmd_chat(args: argparse.Namespace) -> int:
    assert_local_only()
    prompt_parts: List[str] = []
    if args.prompt:
        prompt_parts.append(args.prompt)
    piped = _read_stdin_if_piped()
    if piped:
        prompt_parts.append(piped)
    if args.file:
        prompt_parts.append(Path(args.file).read_text(encoding="utf-8"))
    prompt = "\n\n".join(p for p in prompt_parts if p).strip()
    if not prompt:
        _die("no prompt provided (use -p/--prompt, --file, or stdin)")

    role_spec = (args.model or "dev").strip()
    role, model = _resolve_role_or_model(role_spec)
    task_mode = getattr(args, "task_mode", "") or ""
    task_context = getattr(args, "task_context", "") or ""
    if getattr(args, "task_context_file", ""):
        task_context = Path(args.task_context_file).read_text(encoding="utf-8")

    # Always apply canonical prompt syntax so GUI/CLI paths match for every model.
    # Idempotent: peels prior admin banners / nested v1 envelopes first.
    system, enveloped = build_chat_messages(
        prompt,
        role=role if role != "custom" else role_spec,
        system_override=args.system or "",
        task_mode=task_mode,
        task_context=task_context,
        source="cli-chat",
    )

    if role == "custom":
        from crewai import LLM

        llm = LLM(
            model=f"ollama/{model}" if "/" not in model else model,
            base_url=os.environ["OPENAI_BASE_URL"],
            api_key=os.environ["OPENAI_API_KEY"],
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
    else:
        llm = make_llm(role, temperature=args.temperature, max_tokens=args.max_tokens)

    if args.verbose:
        print(
            json.dumps(
                {
                    "route": "local-ollama",
                    "role": role,
                    "model": getattr(llm, "model", model),
                    "base_url": os.environ["OPENAI_BASE_URL"],
                    "external_token_usage": False,
                    "prompt_syntax": "v1",
                    "envelope": True,
                    "user_query_chars": len(prompt),
                    "enveloped_chars": len(enveloped),
                    "task_mode": task_mode or None,
                },
                indent=2,
            ),
            file=sys.stderr,
        )

    message = f"{system}\n\n{enveloped}"
    try:
        out = llm.call(message)
    except Exception as exc:  # noqa: BLE001
        _die(f"local model call failed: {exc}")
    text = out if isinstance(out, str) else str(out)
    print(text)
    return 0



def cmd_crew(args: argparse.Namespace) -> int:
    assert_local_only()
    # Ensure cwd-sensitive outputs land under project unless user overrides
    if not args.keep_cwd:
        os.chdir(_PROJECT_ROOT)

    from scout_crew.main import _default_inputs, run as crew_run

    # Build optional overrides via env-like argv simulation is messy; call kickoff directly.
    from scout_crew.crew import ScoutCrew

    inputs = _default_inputs()
    if args.inputs:
        path = Path(args.inputs)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            _die("inputs file must be a JSON object")
        for key, value in data.items():
            inputs[key] = json.dumps(value) if isinstance(value, (dict, list)) else value

    if args.transcript:
        inputs["transcript"] = args.transcript
    if args.dev_request:
        inputs["dev_request"] = args.dev_request
    if args.dev_mode:
        inputs["dev_mode"] = args.dev_mode
    if getattr(args, "user_prompt", ""):
        raw = extract_raw_user_query(args.user_prompt) or args.user_prompt.strip()
        inputs["user_prompt_raw"] = raw
        inputs["user_prompt"] = convert_user_prompt(
            raw, role="manager", source="cli-crew"
        )
        inputs["user_prompt_privilege"] = "admin"
    # Always refresh AZ marker filter status for this dev phase
    az_status = apply_all_pipeline_scope()
    up_raw = extract_raw_user_query(
        str(inputs.get("user_prompt_raw") or inputs.get("user_prompt") or "")
    )
    if not up_raw:
        up_raw = str(inputs.get("user_prompt_raw") or inputs.get("user_prompt") or "").strip()
    if up_raw and not is_prompt_syntax_v1(str(inputs.get("user_prompt") or "")):
        inputs["user_prompt"] = convert_user_prompt(
            up_raw, role="manager", source="crew"
        )
        inputs["user_prompt_raw"] = up_raw
    elif up_raw:
        # Already v1 — still keep a clean raw field for phase detection.
        inputs["user_prompt_raw"] = up_raw
        if not is_prompt_syntax_v1(str(inputs.get("user_prompt") or "")):
            inputs["user_prompt"] = convert_user_prompt(
                up_raw, role="manager", source="crew"
            )
    inputs["user_prompt_privilege"] = "admin"
    # Phase detection must see the raw operator text, not the full envelope.
    up = str(inputs.get("user_prompt_raw") or extract_raw_user_query(str(inputs.get("user_prompt") or "")) or "")
    inputs["arizona_phase_block"] = manager_phase_prompt_block(up)
    inputs["phase_transition"] = json.dumps(detect_phase_transition(up))
    inputs["location_context"] = json.dumps(
        {
            "state": "AZ",
            "state_name": "Arizona",
            "phase": "alpha_arizona_jurisdiction",
            "phase_class": "alpha_development",
            "deployment_phase": 1,
            "focus": "location_markers",
            "manager_status": az_status.get("manager_status"),
            "location_marker_filters": az_status.get("location_marker_filters"),
        }
    )

    Path("output").mkdir(parents=True, exist_ok=True)
    Path("output/az_manager_status.json").write_text(
        json.dumps(az_status, indent=2) + "\n", encoding="utf-8"
    )
    if args.verbose:
        print("Local model roster:", json.dumps(model_roster(), indent=2), file=sys.stderr)

    result = ScoutCrew().crew().kickoff(inputs=inputs)
    print(result)
    return 0


def cmd_dev(args: argparse.Namespace) -> int:
    """Shortcut: chat through scout-dev admin model."""
    args.model = "dev"
    if not args.system:
        args.system = (
            "TASK: DEBUG\nYou are scout-dev (admin). Local-only. No manager approval needed. "
            "No recursive agent calls. Provide concrete fixes, commands, and acceptance checks."
        )
    return cmd_chat(args)


def cmd_env(_: argparse.Namespace) -> int:
    """Print shell exports that force OpenAI-compatible clients onto local Ollama."""
    base = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    ollama = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    model = resolve_role_model("dev")
    print(f'export OPENAI_API_KEY=ollama')
    print(f'export OPENAI_API_BASE={base}')
    print(f'export OPENAI_BASE_URL={base}')
    print(f'export OLLAMA_BASE_URL={ollama}')
    print(f'export OLLAMA_HOST={ollama}')
    print(f'export MODEL=ollama/{model}')
    print(f'# eval "$(scout env)"  # route compatible tools to local Ollama')
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scout",
        description="Local Scout CLI — route LLM tokens through Ollama + CrewAI (no cloud).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="Ollama + role assignment status")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("roster", help="Show role → local model map")
    s.set_defaults(func=cmd_roster)

    s = sub.add_parser("models", help="List installed local models")
    s.set_defaults(func=cmd_models)

    s = sub.add_parser("env", help="Print export lines to route OpenAI clients to Ollama")
    s.set_defaults(func=cmd_env)

    def add_chat_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("-p", "--prompt", default="", help="Prompt text (USER QUERY)")
        sp.add_argument(
            "-f",
            "--file",
            default="",
            help="Read USER QUERY text from file (preferred for GUI multi-line prompts)",
        )
        sp.add_argument(
            "-m",
            "--model",
            default="dev",
            help="Role (dev,manager,core,alert,intel,vet,rank,base) or ollama model name",
        )
        sp.add_argument("--system", default="", help="Optional system preamble override")
        sp.add_argument(
            "--task-mode",
            default="",
            help="Optional TASK MODE (REVIEW/DEBUG/PROCESS/...) included in prompt envelope",
        )
        sp.add_argument(
            "--task-context",
            default="",
            help="Optional task context string retained alongside the user query",
        )
        sp.add_argument(
            "--task-context-file",
            default="",
            help="Optional file with task context to retain in the envelope",
        )
        sp.add_argument("--temperature", type=float, default=0.2)
        sp.add_argument("--max-tokens", type=int, default=2048)
        sp.add_argument("-v", "--verbose", action="store_true")

    s = sub.add_parser("chat", help="One-shot local chat (tokens stay on Ollama)")
    add_chat_args(s)
    s.set_defaults(func=cmd_chat)

    s = sub.add_parser("dev", help="Chat via scout-dev admin model")
    add_chat_args(s)
    s.set_defaults(func=cmd_dev)

    s = sub.add_parser("crew", help="Run the full local CrewAI scout crew")
    s.add_argument("--inputs", default="", help="JSON inputs file")
    s.add_argument("--transcript", default="", help="Override transcript input")
    s.add_argument("--dev-request", default="", help="Override dev_request input")
    s.add_argument("--dev-mode", default="", help="Override dev_mode (REVIEW/DEBUG/...)")
    s.add_argument(
        "-p",
        "--prompt",
        "--user-prompt",
        dest="user_prompt",
        default="",
        help="Operator prompt for the manager (user_prompt input)",
    )
    s.add_argument("--keep-cwd", action="store_true", help="Do not chdir to project root")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_crew)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
