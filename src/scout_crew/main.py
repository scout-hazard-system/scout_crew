#!/usr/bin/env python
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from scout_crew.crew import ScoutCrew
from scout_crew.local_llms import model_roster, status

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

DEFAULT_TRANSCRIPT = (
    "Unit 23 copy, running radar on I-5 northbound at mile marker 212, "
    "vehicle stop in progress near the Shell station."
)

DEFAULT_ROUTE_CONTEXT = (
    "origin 48.5126,-122.6127; destination 48.4982,-122.6361; "
    "alternatives=2; shortest_km=7.1; fastest_min=14; "
    "waze_hazards=ok; tool_observations.alerts=[]"
)

DEFAULT_LOCATION_CONTEXT = {
    "city": "Anacortes",
    "state": "WA",
    "desired_types": ["law", "dispatch"],
}

DEFAULT_CHANNEL_CANDIDATES = [
    {"id": "a", "name": "Skagit County Law Dispatch", "state": "WA"},
    {"id": "b", "name": "Miami Fire Tac 3", "state": "FL"},
    {"id": "c", "name": "WSDOT Northwest Traffic", "state": "WA"},
]


def _default_inputs() -> dict:
    return {
        "transcript": DEFAULT_TRANSCRIPT,
        "route_context": DEFAULT_ROUTE_CONTEXT,
        "location_context": json.dumps(DEFAULT_LOCATION_CONTEXT),
        "channel_candidates": json.dumps(DEFAULT_CHANNEL_CANDIDATES),
        "current_year": str(datetime.now().year),
        "topic": "local scout traffic operations",
        "dev_mode": "PROCESS",
        "dev_request": (
            "Review local Scout crew health and propose a short upkeep checklist "
            "for models, Ollama, and crewai run. Note any process gaps."
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
