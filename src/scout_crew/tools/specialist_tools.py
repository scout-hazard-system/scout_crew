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

"""Agentic tool per specialist for the orchestrated manager.

In "orchestrated" mode (`scout crew --orchestrated`) the manager does NOT run the
seven-agent sequential crew. Instead it calls each specialist as a *tool*: the
tool builds the role's PROMPT SYNTAX v1 envelope, binds the role's local/mesh
Ollama model via local_llms.make_llm, and returns the raw specialist answer.

Why:
- The specialists are already one-shot, narrow-contract models (alert/intel/vet/
  rank/core). Routing them through full CrewAI agents duplicates Crew's planner
  machinery for near-zero orchestration gain.
- Consolidating them into manager-callable tools cuts latency, token context
  reuse, and leaves room for the manager's own synthesis budget.
- Every specialist call still obeys the role's contract, its own model/endpoint
  (OLLAMA_HOST_* / SCOUT_PEER_*), and the local-only guard (assert_local_only).

Agentic-tool invariants (do not loosen):
- NON-REASONING: tools bind the /no_think specialist tags and never enable
  thinking; fallbacks stay within the no_think specialist chain. The manager is
  the only reasoning stage.
- LOW TEMPERATURE: every tool pins temperature=0.0 (deterministic contracts);
  the manager cannot pass a temperature through a tool argument.
- NON-PERSONA: each tool substitutes a neutral contract system prompt (no role
  persona/backstory, no "you are scout-X" framing) — the specialist acts as a
  pure contract executor, not a character.

Tools never write to the blackboard themselves — the manager synthesizes and
writes the summary/rewrite per blackboard ACL.
"""

from __future__ import annotations

from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from scout_crew.local_llms import assert_local_only, make_llm
from scout_crew.prompt_syntax import build_chat_messages

# Role -> contract-only system prompt + per-call budget (temperature pinned 0.0:
# deterministic contracts, non-reasoning tags, non-persona system).
SPECIALIST_ROLES = {
    "alert": {
        "max_tokens": 1024,
        "system": (
            "You are the traffic-enforcement decision step. Apply the exact "
            "output contract; nothing else."
        ),
        "description": (
            "Call the scout-alert decision step. Give it a scanner transcript and "
            "it returns either exactly 'IGNORE' or one 'ALERT: ...' sentence with "
            "verbatim enforcement locations. Deterministic (temperature 0, no "
            "thinking, no persona). Use for traffic-enforcement decisioning."
        ),
    },
    "intel": {
        "max_tokens": 1536,
        "system": (
            "You are the dispatch-intel extraction step. Apply the exact JSON "
            "output contract; nothing else."
        ),
        "description": (
            "Call the scout-intel extraction step. Give it a scanner transcript and "
            "it returns STRICT JSON with keys call_types, priority, codes, units, "
            "locations, pois, summary. Deterministic. Use to extract structured "
            "dispatch intel."
        ),
    },
    "vet": {
        "max_tokens": 768,
        "system": (
            "You are the alert-vetting gate step. Apply the exact pass/fail "
            "output contract; nothing else."
        ),
        "description": (
            "Call the scout-vet gate step. Give it a transcript (and a proposed "
            "ALERT line when you have one) and it returns exactly 'VET_PASS' or "
            "'VET_FAIL'. Deterministic. Use to gate a proposed alert on clear "
            "roadway enforcement or an immediate driving hazard."
        ),
    },
    "rank": {
        "max_tokens": 1536,
        "system": (
            "You are the channel-ranking step. Apply the exact JSON output "
            "contract; nothing else."
        ),
        "description": (
            "Call the scout-rank step. Give it the location context JSON and the "
            "channel_candidates JSON and it returns compact ranking JSON "
            '{"ranked":[...],"top_id":"..."}. Deterministic; never invent '
            "candidates."
        ),
    },
    "core": {
        "max_tokens": 2048,
        "system": (
            "You are the driver-package build step. Apply the exact JSON output "
            "contract; nothing else."
        ),
        "description": (
            "Call the scout-core package step. Give it route context, the "
            "transcript, and any alert/intel/vet/rank results you already have, "
            "and it returns the driver-facing JSON package (nav_line, chat, "
            "alert, vet, intel, channels, manager_notes). Deterministic. Use as "
            "the operational package builder."
        ),
    },
}

# Appended to the manager synthesis task when orchestrated mode is on: specialists
# are reached through tools, not separate CrewAI tasks with DAG context.
ORCHESTRATED_SYNTHESIS_OVERRIDE = """
=== ORCHESTRATED MODE (manager calls specialists as tools) ===
You operate with the specialist tools: specialist_alert, specialist_intel,
specialist_vet, specialist_rank, specialist_core.

To complete synthesis:
1. Deliver the driver package via specialist_core: give it route context, the
   transcript, and any alert/intel/vet/rank findings you gathered.
2. When the transcript may contain traffic enforcement, in order:
   - specialist_alert(transcript) for the ALERT:/IGNORE decision,
   - specialist_vet(transcript + proposed ALERT line) to gate it,
   - specialist_intel(transcript) for structured dispatch intel.
3. specialist_rank(location_context + channel_candidates) for channel ranking.
4. Verify each tool result is not an ERROR. If a specialist failed, set that
   field to {} / "IGNORE" and record the gap in open_task_items instead of
   inventing facts.

There are NO specialist tasks in context in this mode: gather specialist outputs
exclusively through these tools, then produce the required synthesis JSON below.
"""


class _SpecialistIn(BaseModel):
    prompt: str = Field(
        ...,
        description=(
            "Full prompt for this specialist: include the transcript / context / "
            "candidates it needs. The tool applies the role's prompt syntax."
        ),
    )


class SpecialistToolBase(BaseTool):
    """Tool that routes a prompt to a single specialist model (local/mesh).

    Two fields the manager can never change through tool arguments:
    - temperature is pinned to 0.0 (deterministic contracts)
    - role_key selects the non-reasoning /no_think specialist tag
    The non-persona system prompt is applied for every call.
    """

    args_schema: Type[BaseModel] = _SpecialistIn
    role_key: str = "alert"
    system: str = ""
    temperature: float = 0.0
    max_tokens: int = 1024

    def _run(self, prompt: str) -> str:
        prompt = (prompt or "").strip()
        if not prompt:
            return "ERROR: empty prompt."
        try:
            assert_local_only()
            system_prompt = self.system or "Apply the exact output contract."
            system, enveloped = build_chat_messages(
                prompt,
                role="custom",
                system_override=system_prompt,
                source="orchestrated-manager",
            )
            llm = make_llm(
                self.role_key,
                temperature=self.temperature,  # always 0.0
                max_tokens=self.max_tokens,
            )
            out = llm.call(f"{system}\n\n{enveloped}")
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: specialist_{self.role_key} failed: {exc}"
        return str(out)


def specialist_tools_for_orchestration() -> list:
    """Return one SpecialistTool instance per specialist role (manager-visible)."""
    tools = []
    for role, cfg in SPECIALIST_ROLES.items():
        # Bake name/description + per-role pydantic field defaults into a
        # dedicated subclass so CrewAI validates and instances carry no kwargs.
        subclass = type(
            f"Specialist{role.title()}Tool",
            (SpecialistToolBase,),
            {
                "name": f"specialist_{role}",
                "description": cfg["description"],
                "role_key": role,
                "system": cfg["system"],
                "temperature": 0.0,
                "max_tokens": cfg["max_tokens"],
            },
        )
        tools.append(subclass())
    return tools


__all__ = [
    "ORCHESTRATED_SYNTHESIS_OVERRIDE",
    "SPECIALIST_ROLES",
    "SpecialistToolBase",
    "specialist_tools_for_orchestration",
]