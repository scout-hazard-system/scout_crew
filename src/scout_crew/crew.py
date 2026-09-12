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

import os

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from scout_crew.tools import orchestrated_manager_tools, tools_for_role
from scout_crew.admin_policy import (
    ADMIN_AGENT_KEYS,
    ANTI_RECURSION_RULES,
    agent_runtime_kwargs,
    validate_admin_partition,
    validate_task_context_dag,
)
from scout_crew.local_llms import assert_local_only, make_llm
from scout_crew.tools.specialist_tools import ORCHESTRATED_SYNTHESIS_OVERRIDE


def _env_flag(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _with_policy_text(config: dict, *, admin: bool) -> dict:
    """Copy agent YAML config and append anti-recursion (+ admin privilege) rules."""
    from scout_crew.admin_policy import ADMIN_AUTHORITY, USER_PROMPT_ADMIN_PRIVILEGE

    cfg = dict(config)
    backstory = str(cfg.get("backstory", "")).rstrip()
    if admin:
        parts = [ADMIN_AUTHORITY, USER_PROMPT_ADMIN_PRIVILEGE, ANTI_RECURSION_RULES]
    else:
        parts = [ANTI_RECURSION_RULES]
    cfg["backstory"] = backstory + chr(10) + chr(10) + (chr(10) + chr(10)).join(parts)
    return cfg


@CrewBase
class ScoutCrew:
    """Local Scout crew: sequential pipeline, admin manager+dev, no recursion loops.

    Default mode runs the seven-agent sequential pipeline. With
    SCOUT_ORCHESTRATED=1 (scout crew --orchestrated) the manager drives the
    alert/intel/vet/rank/core specialists as *tools* instead of separate tasks —
    same contracts, fewer agents, manager-owned synthesis.
    """

    agents: list[BaseAgent]
    tasks: list[Task]

    def _build_agent(
        self,
        key: str,
        role_llm: str,
        temperature: float,
        max_tokens: int,
        tools: list | None = None,
    ) -> Agent:
        admin = key in ADMIN_AGENT_KEYS
        config = _with_policy_text(self.agents_config[key], admin=admin)  # type: ignore[index]
        kwargs = agent_runtime_kwargs(key)
        # Shared multi-machine blackboard tools (role-ACL enforced in tool/store).
        # specialists/core -> write pipeline; manager -> summarize/rewrite pipeline;
        # dev -> dev_debug only; hermes (external) would be read-only via tools_for_role.
        if tools is None:
            tools = tools_for_role(key)
        return Agent(
            config=config,  # type: ignore[arg-type]
            llm=make_llm(role_llm, temperature=temperature, max_tokens=max_tokens),
            tools=tools,
            verbose=True,
            **kwargs,
        )

    @agent
    def local_manager(self) -> Agent:
        # Admin: synthesizes final brief; may one-hop consult specialists only.
        # In orchestrated mode the manager gets one agentic tool per specialist.
        tools = orchestrated_manager_tools() if _env_flag("SCOUT_ORCHESTRATED") else None
        return self._build_agent("local_manager", "manager", temperature=0.1, max_tokens=3072, tools=tools)

    @agent
    def dev_specialist(self) -> Agent:
        # Admin: debug/process/dev work without manager approval on its own task.
        return self._build_agent("dev_specialist", "dev", temperature=0.2, max_tokens=3072)

    @agent
    def alert_specialist(self) -> Agent:
        # Qwen3 may emit internal reasoning before the contract line; keep headroom.
        return self._build_agent("alert_specialist", "alert", temperature=0.0, max_tokens=1024)

    @agent
    def intel_specialist(self) -> Agent:
        return self._build_agent("intel_specialist", "intel", temperature=0.0, max_tokens=1536)

    @agent
    def vet_specialist(self) -> Agent:
        return self._build_agent("vet_specialist", "vet", temperature=0.0, max_tokens=768)

    @agent
    def rank_specialist(self) -> Agent:
        return self._build_agent("rank_specialist", "rank", temperature=0.0, max_tokens=1536)

    @agent
    def core_specialist(self) -> Agent:
        return self._build_agent("core_specialist", "core", temperature=0.1, max_tokens=2048)

    @task
    def alert_task(self) -> Task:
        return Task(config=self.tasks_config["alert_task"])  # type: ignore[index]

    @task
    def intel_task(self) -> Task:
        return Task(config=self.tasks_config["intel_task"])  # type: ignore[index]

    @task
    def vet_task(self) -> Task:
        return Task(config=self.tasks_config["vet_task"])  # type: ignore[index]

    @task
    def rank_task(self) -> Task:
        return Task(config=self.tasks_config["rank_task"])  # type: ignore[index]

    @task
    def core_task(self) -> Task:
        return Task(config=self.tasks_config["core_task"])  # type: ignore[index]

    @task
    def dev_task(self) -> Task:
        return Task(
            config=self.tasks_config["dev_task"],  # type: ignore[index]
            output_file="output/dev_brief.md",
        )

    @task
    def manager_synthesis_task(self) -> Task:
        return Task(
            config=self.tasks_config["manager_synthesis_task"],  # type: ignore[index]
            output_file="output/local_brief.json",
        )

    @crew
    def crew(self) -> Crew:
        """Sequential crew: fixed task owners, admin manager+dev, loop-safe.

        SCOUT_ORCHESTRATED=1 switches to orchestrated mode: specialists are tools
        on the manager and only dev_task + manager_synthesis_task run.
        """
        assert_local_only()
        # Prefer raw YAML for DAG checks (CrewBase may hydrate context into Task objs).
        import yaml
        from pathlib import Path as _P

        yaml_path = _P(__file__).resolve().parent / "config" / "tasks.yaml"
        raw_tasks = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        validate_task_context_dag(raw_tasks)

        orchestrated = _env_flag("SCOUT_ORCHESTRATED")
        if orchestrated:
            roster_keys = ["local_manager", "dev_specialist"]
        else:
            roster_keys = [
                "local_manager",
                "dev_specialist",
                "alert_specialist",
                "intel_specialist",
                "vet_specialist",
                "rank_specialist",
                "core_specialist",
            ]
        validate_admin_partition(roster_keys)

        if orchestrated:
            # Only admin agents run; specialists are reached via manager tools.
            agents = [self.local_manager(), self.dev_specialist()]
            dev_task = self.dev_task()
            # Specialist tasks don't exist in this DAG — drop their stale context.
            dev_task.context = []
            mgr_task = self.manager_synthesis_task()
            mgr_task.context = [dev_task]
            mgr_task.description = (
                (mgr_task.description or "")
                + ORCHESTRATED_SYNTHESIS_OVERRIDE
            )
            tasks: list[Task] = [dev_task, mgr_task]
        else:
            # Explicit roster (includes admins). Sequential process uses task.agent
            # bindings so work is not re-routed through a hierarchical manager loop.
            agents = [
                self.local_manager(),
                self.dev_specialist(),
                self.alert_specialist(),
                self.intel_specialist(),
                self.vet_specialist(),
                self.rank_specialist(),
                self.core_specialist(),
            ]
            tasks = self.tasks

        return Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            verbose=True,
            memory=False,
            cache=True,
            planning=False,
            max_rpm=30,
        )
