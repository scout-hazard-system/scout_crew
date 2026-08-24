#!/usr/bin/env python
# Copyright 2026 Scout Project Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
import os as _os
_os.environ.setdefault("CREWAI_TRACING_ENABLED", "true")
if _os.getenv("CREWAI_TRACING_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
    _os.environ["CREWAI_TRACING_ENABLED"] = "true"

from scout_crew.arizona_phase import manager_phase_prompt_block
from scout_crew.crew import ScoutCrew
from scout_crew.local_llms import model_roster, status
from scout_crew.prompt_syntax import convert_user_prompt, extract_raw_user_query

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

DEFAULT_TRANSCRIPT = (
    "Unit 23 copy, running radar on I-5 northbound at mile marker 212, "
    "vehicle stop in progress near the Shell station."
)

DEFAULT_ROUTE_CONTEXT = (
    "origin 33.4484,-112.0740; destination 33.4942,-111.9261; "
    "alternatives=2; shortest_km=18.4; fastest_min=22; "
    "waze_hazards=ok; jurisdiction=AZ; tool_observations.alerts=[]"
)

DEFAULT_LOCATION_CONTEXT = {
    "city": "Phoenix",
    "state": "AZ",
    "state_name": "Arizona",
    "county": "Maricopa County",
    "desired_types": ["law", "dispatch"],
    "phase": "alpha_arizona_jurisdiction",
    "focus": "arizona_jurisdiction",
}

DEFAULT_CHANNEL_CANDIDATES = [
    {"id": "a", "name": "Phoenix Police", "state": "AZ"},
    {"id": "b", "name": "Coconino South Sheriff, DPS and Forest Service", "state": "AZ"},
    {"id": "c", "name": "Arizona DPS", "state": "AZ"},
]


def _default_inputs() -> dict:
    return {
        "transcript": DEFAULT_TRANSCRIPT,
        "route_context": DEFAULT_ROUTE_CONTEXT,
        "location_context": json.dumps(DEFAULT_LOCATION_CONTEXT),
        "channel_candidates": json.dumps(DEFAULT_CHANNEL_CANDIDATES),
        "current_year": str(datetime.now().year),
        "topic": "alpha arizona jurisdiction operations",
        "dev_mode": "PROCESS",
        "dev_request": (
            "Alpha development: hold AZ-only jurisdiction with all facets functional. "
            "Scanner/hazard/ranking essential inside AZ. "
            "Stay in alpha until explicit second deployment phase prompt. "
            "Checklist for AZ jurisdiction ops + phase lock."
        ),
"user_prompt": convert_user_prompt(
            "Alpha development check: confirm phase_class=alpha_development is held, "
            "Arizona jurisdiction is active, AZ marker filters are set, and scanner/hazard "
            "remain essential inside AZ only. Do not leave alpha unless this prompt "
            "explicitly starts deployment phase 2. Answer first, then finish the brief.",
            role="manager",
            source="defaults",
        ),
        "user_prompt_raw": (
            "Alpha development check: confirm phase_class=alpha_development is held, "
            "Arizona jurisdiction is active, AZ marker filters are set, and scanner/hazard "
            "remain essential inside AZ only. Do not leave alpha unless this prompt "
            "explicitly starts deployment phase 2. Answer first, then finish the brief."
        ),
        "user_prompt_privilege": "admin",
        "prompt_syntax": "v1",
        "arizona_phase_block": manager_phase_prompt_block(
            "Alpha development check: hold alpha until second deployment phase is explicitly announced."
        ),
    }




def _load_inputs_from_argv() -> dict:
    inputs = _default_inputs()
    if len(sys.argv) >= 2 and sys.argv[1] not in {"status", "roster"}:
        path = Path(sys.argv[1])
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Input file must contain a JSON object")
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    inputs[key] = json.dumps(value)
                else:
                    inputs[key] = value
    # Normalize any loaded user_prompt into PROMPT SYNTAX v1 (idempotent).
    # Prefer explicit user_prompt from the file when present; do not keep a
    # stale default user_prompt_raw that would shadow a loaded banner/envelope.
    loaded_up = str(inputs.get("user_prompt") or "")
    loaded_raw = str(inputs.get("user_prompt_raw") or "")
    # If user_prompt looks like a banner/envelope (or differs from default raw),
    # peel from user_prompt first.
    candidate = loaded_up or loaded_raw
    if loaded_raw and loaded_up and loaded_raw not in loaded_up and not loaded_up.startswith(
        "==="
    ):
        # File supplied a clean raw plus unrelated wrapped prompt — trust raw.
        candidate = loaded_raw
    elif loaded_up.startswith("===") or "USER QUERY" in loaded_up or "ADMIN-PRIVILEGED" in loaded_up:
        candidate = loaded_up
    elif loaded_raw:
        candidate = loaded_raw
    raw = extract_raw_user_query(candidate)
    if raw:
        inputs["user_prompt_raw"] = raw
        inputs["user_prompt"] = convert_user_prompt(
            raw, role="manager", source="main"
        )
        inputs["user_prompt_privilege"] = "admin"
        inputs["prompt_syntax"] = "v1"
    return inputs


def show_status() -> None:
    print(json.dumps(status(), indent=2))


def show_roster() -> None:
    print(json.dumps(model_roster(), indent=2))


def run() -> None:
    """Run the local-only scout crew."""
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        show_status()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "roster":
        show_roster()
        return

    Path("output").mkdir(parents=True, exist_ok=True)
    inputs = _load_inputs_from_argv()
    print("Local model roster:", json.dumps(model_roster(), indent=2))
    try:
        result = ScoutCrew().crew().kickoff(inputs=inputs)
        print("\n=== FINAL RESULT ===")
        print(result)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}") from e


def train() -> None:
    inputs = _default_inputs()
    try:
        ScoutCrew().crew().train(
            n_iterations=int(sys.argv[1]),
            filename=sys.argv[2],
            inputs=inputs,
        )
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}") from e


def replay() -> None:
    try:
        ScoutCrew().crew().replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}") from e


def test() -> None:
    inputs = _default_inputs()
    try:
        ScoutCrew().crew().test(
            n_iterations=int(sys.argv[1]),
            eval_llm=sys.argv[2] if len(sys.argv) > 2 else "ollama/llama3.1",
            inputs=inputs,
        )
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}") from e


def run_with_trigger() -> None:
    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")
    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        raise Exception("Invalid JSON payload provided as argument") from e

    inputs = _default_inputs()
    inputs["crewai_trigger_payload"] = trigger_payload
    if isinstance(trigger_payload, dict):
        for key in (
            "transcript",
            "route_context",
            "location_context",
            "channel_candidates",
        ):
            if key in trigger_payload:
                value = trigger_payload[key]
                inputs[key] = json.dumps(value) if isinstance(value, (dict, list)) else value

    Path("output").mkdir(parents=True, exist_ok=True)
    try:
        return ScoutCrew().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}") from e


if __name__ == "__main__":
    run()
