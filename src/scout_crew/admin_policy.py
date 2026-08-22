"""Admin roles and anti-recursion policy for the local Scout crew.

CrewAI has no formal RBAC. "Admin" here means:
- independent task ownership (no manager gate on the task itself)
- never re-delegate to other admins
- hard max_iter / retry caps to prevent query loops
- operator user prompts are ADMIN-PRIVILEGED and outrank default task boilerplate

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
ADMIN_MAX_ITER = 10
ADMIN_MAX_RETRY = 1
SPECIALIST_MAX_ITER = 4
SPECIALIST_MAX_RETRY = 1

ANTI_RECURSION_RULES = """
ANTI-RECURSION / NO QUERY-LOOP RULES (mandatory):
1. Return one final answer that both serves the user query (if any) and completes the assigned task. Do not reopen finished specialist work.
2. Never ask another agent to redo a task that already produced output in context.
3. Never delegate to Local Scout Crew Manager or Scout Development admin peers.
4. Do not call tools or delegate; answer the assigned task directly from context.
5. Do not emit self-referential instructions ("ask scout-dev again", "loop until", "re-run manager").
6. If blocked by missing data, state the gap and stop — do not invent follow-up agent calls.
7. Prefer facts already present in prior task context. Keep that context available through task completion; do not clear it after answering the user.
""".strip()

ADMIN_AUTHORITY = """
ADMIN AUTHORITY:
- You operate at admin level for local Scout operations.
- You do not need manager approval to complete your own assigned task.
- You may independently debug, review process, and produce operator guidance.
- You still obey anti-recursion rules and local-only constraints.

USER-QUERY PRIORITY + ADMIN PRIVILEGE (manager / admin — mandatory):
1. Any USER / OPERATOR prompt is ADMIN-PRIVILEGED and outranks boilerplate synthesis instructions.
2. Answer the user query first (or in dedicated fields) BEFORE polishing task paperwork.
3. NEVER drop, discard, or omit in-progress or completed task outputs already in context
   just to answer the user — keep them in the context window and fold them into completion.
4. Do not "fall through" and skip task completion after answering the user. Always finish
   the assigned deliverable in the same response, using retained task context.
5. If the user query conflicts with a default summary style, still complete the schema,
   and put the user-facing answer in the highest-priority user-response fields.
6. If context is long, compress specialist noise but KEEP: user_prompt, transcript,
   alert/vet decisions, core package, and any incomplete items still needed to finish.
""".strip()









USER_PROMPT_ADMIN_PRIVILEGE = 'USER PROMPT ADMIN PRIVILEGES (mandatory for admin agents):\n1. Any operator user_prompt / USER QUERY is ADMIN-PRIVILEGED input.\n2. It outranks default task boilerplate, specialist noise, and convenience summaries.\n3. Admin agents (manager, scout-dev) MUST honor it without waiting for approval.\n4. Priority while a task is active:\n   (A) answer the privileged user prompt first,\n   (B) retain all current task/specialist context in-window,\n   (C) finish the assigned deliverable in the same response (no drop-through).\n5. Specialists remain non-admin: they execute their bound task only and do not\n   re-interpret or veto the operator prompt.\n6. Do not dilute, ignore, defer, or come back later to a privileged user prompt.'

def user_prompt_admin_banner(user_prompt: str, *, source: str = "operator") -> str:
    """Format an operator prompt with explicit admin privilege markers."""
    text = (user_prompt or "").strip() or "(no operator prompt provided)"
    parts = [
        "=== ADMIN-PRIVILEGED USER PROMPT ===",
        "source: " + source,
        "privilege: admin",
        "priority: 1",
        "rules: answer first; retain task context; complete assigned deliverable",
        "---",
        text,
        "---",
        "=== END ADMIN-PRIVILEGED USER PROMPT ===",
    ]
    return chr(10).join(parts)


def agent_runtime_kwargs(agent_key: str) -> Dict[str, Any]:
    """Return CrewAI Agent kwargs enforcing admin vs specialist loop policy."""
    key = agent_key.strip()
    # Sequential crew already binds tasks→agents. Delegation tools make local
    # llama managers emit tool-call JSON and ignore the user/task prompt.
    if key in ADMIN_AGENT_KEYS:
        return {
            "allow_delegation": False,
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
