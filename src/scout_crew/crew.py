from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from scout_crew.admin_policy import (
    ADMIN_AGENT_KEYS,
    ANTI_RECURSION_RULES,
    agent_runtime_kwargs,
    validate_admin_partition,
    validate_task_context_dag,
)
from scout_crew.local_llms import assert_local_only, make_llm


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
    """Local Scout crew: sequential pipeline, admin manager+dev, no recursion loops."""

    agents: list[BaseAgent]
    tasks: list[Task]

    def _build_agent(self, key: str, role_llm: str, temperature: float, max_tokens: int) -> Agent:
        admin = key in ADMIN_AGENT_KEYS
        config = _with_policy_text(self.agents_config[key], admin=admin)  # type: ignore[index]
        kwargs = agent_runtime_kwargs(key)
        return Agent(
            config=config,  # type: ignore[arg-type]
            llm=make_llm(role_llm, temperature=temperature, max_tokens=max_tokens),
            verbose=True,
            **kwargs,
        )

    @agent
    def local_manager(self) -> Agent:
        # Admin: synthesizes final brief; may one-hop consult specialists only.
        return self._build_agent("local_manager", "manager", temperature=0.1, max_tokens=3072)

    @agent
    def dev_specialist(self) -> Agent:
        # Admin: debug/process/dev work without manager approval on its own task.
        return self._build_agent("dev_specialist", "dev", temperature=0.2, max_tokens=3072)

    @agent
    def alert_specialist(self) -> Agent:
        return self._build_agent("alert_specialist", "alert", temperature=0.0, max_tokens=512)

    @agent
    def intel_specialist(self) -> Agent:
        return self._build_agent("intel_specialist", "intel", temperature=0.0, max_tokens=1024)

    @agent
    def vet_specialist(self) -> Agent:
        return self._build_agent("vet_specialist", "vet", temperature=0.0, max_tokens=64)

    @agent
    def rank_specialist(self) -> Agent:
        return self._build_agent("rank_specialist", "rank", temperature=0.0, max_tokens=1024)

    @agent
    def core_specialist(self) -> Agent:
        return self._build_agent("core_specialist", "core", temperature=0.1, max_tokens=1536)

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
        """Sequential crew: fixed task owners, admin manager+dev, loop-safe."""
        assert_local_only()
        # Prefer raw YAML for DAG checks (CrewBase may hydrate context into Task objs).
        import yaml
        from pathlib import Path as _P

        yaml_path = _P(__file__).resolve().parent / "config" / "tasks.yaml"
        raw_tasks = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        validate_task_context_dag(raw_tasks)
        validate_admin_partition(
            [
                "local_manager",
                "dev_specialist",
                "alert_specialist",
                "intel_specialist",
                "vet_specialist",
                "rank_specialist",
                "core_specialist",
            ]
        )

        # Explicit roster (includes admins). Sequential process uses task.agent bindings
        # so work is not re-routed through a hierarchical manager planner loop.
        roster = [
            self.local_manager(),
            self.dev_specialist(),
            self.alert_specialist(),
            self.intel_specialist(),
            self.vet_specialist(),
            self.rank_specialist(),
            self.core_specialist(),
        ]

        return Crew(
            agents=roster,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            memory=False,
            cache=True,
            planning=False,
            max_rpm=30,
        )
