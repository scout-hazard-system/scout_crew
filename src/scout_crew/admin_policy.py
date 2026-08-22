"""Admin roles and anti-recursion policy for the local Scout crew.

CrewAI has no formal RBAC. "Admin" here means:
- independent task ownership (no manager gate on the task itself)
- optional one-hop consult of non-admin specialists
- never re-delegate to other admins
- hard max_iter / retry caps to prevent query loops

Process must be sequential with explicit task→agent bindings so the hierarchical
manager cannot re-plan and re-query the same work in a loop.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set

# Agents that may consult specialists once. Never each other.
ADMIN_AGENT_KEYS = frozenset({"local_manager", "dev_specialist"})

# Specialists must never delegate (breaks circular handoffs).
SPECIALIST_AGENT_KEYS = frozenset(
    {
        "alert_specialist",
        "intel_specialist",
        "vet_specialist",
        "rank_specialist",
        "core_specialist",
    }
)

# Tight caps — admins get more room for debug/synthesis, not infinite loops.
ADMIN_MAX_ITER = 8
ADMIN_MAX_RETRY = 1
SPECIALIST_MAX_ITER = 4
SPECIALIST_MAX_RETRY = 1

ANTI_RECURSION_RULES = """
ANTI-RECURSION / NO QUERY-LOOP RULES (mandatory):
1. Do your assigned task once and return a final answer. Do not reopen finished work.
2. Never ask another agent to redo a task that already produced output in context.
3. Never delegate to Local Scout Crew Manager or Scout Development admin peers.
4. If you may consult, consult a non-admin specialist at most once, then decide yourself.
5. Do not emit self-referential instructions ("ask scout-dev again", "loop until", "re-run manager").
6. If blocked by missing data, state the gap and stop — do not invent follow-up agent calls.
7. Prefer the facts already present in prior task context over new side questions.
""".strip()

ADMIN_AUTHORITY = """
ADMIN AUTHORITY:
- You operate at admin level for local Scout operations.
- You do not need manager approval to complete your own assigned task.
- You may independently debug, review process, and produce operator guidance.
- You still obey anti-recursion rules and local-only constraints.
""".strip()


def agent_runtime_kwargs(agent_key: str) -> Dict[str, Any]:
    """Return CrewAI Agent kwargs enforcing admin vs specialist loop policy."""
    key = agent_key.strip()
    if key in ADMIN_AGENT_KEYS:
        return {
            "allow_delegation": True,
            "max_iter": ADMIN_MAX_ITER,
            "max_retry_limit": ADMIN_MAX_RETRY,
            "respect_context_window": True,
            "cache": True,
        }
    return {
        "allow_delegation": False,
        "max_iter": SPECIALIST_MAX_ITER,
        "max_retry_limit": SPECIALIST_MAX_RETRY,
        "respect_context_window": True,
        "cache": True,
    }


def _context_dep_name(dep: Any) -> str:
    """Normalize a context dependency to a task key name."""
    if isinstance(dep, str):
        # CrewBase sometimes stringifies Task objects; pull name='...' if present.
        if "name='" in dep:
            try:
                return dep.split("name='", 1)[1].split("'", 1)[0]
            except Exception:
                return dep
        return dep
    name = getattr(dep, "name", None)
    if isinstance(name, str) and name:
        return name
    return str(dep)


def validate_task_context_dag(tasks_config: Dict[str, Any]) -> None:
    """Raise if task context edges form a cycle (would create execution loops)."""
    graph: Dict[str, List[str]] = {}
    for name, cfg in tasks_config.items():
        deps: List[str] = []
        if isinstance(cfg, dict):
            raw = cfg.get("context") or []
            if isinstance(raw, list):
                deps = [_context_dep_name(d) for d in raw]
        graph[str(name)] = deps

    visiting: Set[str] = set()
    visited: Set[str] = set()

    def dfs(node: str, stack: List[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            cycle = " -> ".join(stack + [node])
            raise RuntimeError(f"Task context cycle detected (recursion risk): {cycle}")
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep not in graph:
                # Unknown dependency name — fail fast
                raise RuntimeError(f"Task '{node}' context references unknown task '{dep}'")
            dfs(dep, stack + [node])
        visiting.remove(node)
        visited.add(node)

    for task_name in graph:
        dfs(task_name, [])


def validate_admin_partition(agent_keys: Iterable[str]) -> None:
    keys = set(agent_keys)
    unknown_admins = ADMIN_AGENT_KEYS - keys
    # admins may be constructed even if not all present; only check overlap mistakes
    overlap = ADMIN_AGENT_KEYS & SPECIALIST_AGENT_KEYS
    if overlap:
        raise RuntimeError(f"Admin/specialist partition overlap: {sorted(overlap)}")
    for key in keys:
        if key not in ADMIN_AGENT_KEYS and key not in SPECIALIST_AGENT_KEYS:
            # allow only known sets
            raise RuntimeError(f"Unknown agent key outside admin/specialist policy: {key}")
