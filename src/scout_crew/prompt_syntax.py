"""Canonical prompt envelope for scout CLI/GUI chat across all model roles.

Ensures user queries are explicitly framed and always reach the model, including
when role-specific task syntax (ALERT/VET/JSON/etc.) also applies.
"""

from __future__ import annotations

from typing import Dict, Optional

# Roles the GUI/CLI expose
CHAT_ROLES = (
    "manager",
    "dev",
    "core",
    "alert",
    "intel",
    "vet",
    "rank",
    "base",
)

ROLE_ALIASES = {
    "manager": "manager",
    "mgr": "manager",
    "admin": "manager",
    "dev": "dev",
    "scout-dev": "dev",
    "core": "core",
    "nav": "core",
    "chat": "core",
    "alert": "alert",
    "intel": "intel",
    "vet": "vet",
    "rank": "rank",
    "base": "base",
    "llama": "base",
    "llama3.1": "base",
}

ROLE_SYSTEM_PROMPTS: Dict[str, str] = {
    "manager": (
        "You are the Local Scout Crew Manager (admin) on local Ollama only.\n"
        "PROMPT SYNTAX:\n"
        "- Sections marked === USER QUERY === are ADMIN-PRIVILEGED highest priority — answer fully with admin authority.\n"
        "- If === TASK CONTEXT === is present, retain it and finish any requested deliverable "
        "in the same reply after the user answer (no drop-through).\n"
        "- Do not emit tool calls or name/parameters envelopes unless the user asks for JSON.\n"
        "Keep scanner/hazard facets on within AZ jurisdictions.\n- ALPHA DEVELOPMENT LOCK: remain in alpha persona/mindset until the user explicitly notifies the second deployment phase.\n- DEV PHASE: set ALL location marker filters for the Arizona (AZ) shard; scanner/hazard are essential inside AZ only; non-AZ out of scope.\nBe concise and operational."
    ),
    "dev": (
        "You are scout-dev (admin) on local Ollama only.\n"
        "PROMPT SYNTAX:\n"
        "- === USER QUERY === is ADMIN-PRIVILEGED and mandatory to answer without approval.\n"
        "- Optional === TASK MODE === (REVIEW/DEBUG/IMPLEMENT/PROCESS/TEST/DOCS) guides format.\n"
        "- No manager approval. No tool-call envelopes unless JSON is requested."
    ),
    "core": (
        "You are scout-core on local Ollama only.\n"
        "PROMPT SYNTAX:\n"
        "- === USER QUERY === must be answered from provided facts only.\n"
        "- If the query is NAV/CHAT shaped, follow scout-core contracts; otherwise answer directly."
    ),
    "alert": (
        "You are scout-alert on local Ollama only.\n"
        "PROMPT SYNTAX:\n"
        "- === USER QUERY === is mandatory.\n"
        "- If it contains a scanner transcript / enforcement question, reply ALERT: ... or IGNORE.\n"
        "- Otherwise answer the user query directly."
    ),
    "intel": (
        "You are scout-intel on local Ollama only.\n"
        "PROMPT SYNTAX:\n"
        "- === USER QUERY === is mandatory.\n"
        "- For transcript intel extraction, return strict intel JSON; otherwise answer directly."
    ),
    "vet": (
        "You are scout-vet on local Ollama only.\n"
        "PROMPT SYNTAX:\n"
        "- === USER QUERY === is mandatory.\n"
        "- For alert vetting, prefer exactly VET_PASS or VET_FAIL; otherwise answer directly."
    ),
    "rank": (
        "You are scout-rank on local Ollama only.\n"
        "PROMPT SYNTAX:\n"
        "- === USER QUERY === is mandatory.\n"
        "- For channel ranking requests, return compact ranking JSON; otherwise answer directly."
    ),
    "base": (
        "You are a local Ollama assistant (llama base).\n"
        "PROMPT SYNTAX:\n"
        "- === USER QUERY === is mandatory — answer it fully.\n"
        "- No cloud APIs. No tool-call envelopes unless asked."
    ),
    "custom": (
        "You are a local Ollama model.\n"
        "PROMPT SYNTAX:\n"
        "- === USER QUERY === is mandatory — answer it fully.\n"
        "- Stay local-only."
    ),
}

# Optional role-specific leading task hint when user didn't supply one
ROLE_TASK_HINTS: Dict[str, str] = {
    "manager": "Answer the operator; if a brief is implied, complete it after the answer.",
    "dev": "Prefer TASK-style structure when helpful (REVIEW/DEBUG/IMPLEMENT/PROCESS/TEST/DOCS).",
    "core": "Use NAV one-liner or CHAT JSON only when the user asks for those contracts.",
    "alert": "Use ALERT:/IGNORE when the user provides a transcript to classify.",
    "intel": "Use intel JSON schema when extracting dispatch structure.",
    "vet": "Use VET_PASS/VET_FAIL when vetting a proposed alert.",
    "rank": "Use ranking JSON when scoring channel candidates.",
    "base": "Answer helpfully and directly.",
    "custom": "Answer helpfully and directly.",
}


PROMPT_SYNTAX_MARKER = "=== PROMPT SYNTAX v1 ==="
ADMIN_BANNER_MARKER = "=== ADMIN-PRIVILEGED USER PROMPT ==="
USER_QUERY_START = "=== USER QUERY (ADMIN-PRIVILEGED) ==="
USER_QUERY_END = "=== END USER QUERY ==="
USER_QUERY_REMINDER = "=== USER QUERY REMINDER (ADMIN-PRIVILEGED, still priority 1) ==="


def normalize_role(spec: str) -> str:
    key = (spec or "dev").strip().lower()
    if key in ROLE_ALIASES:
        return ROLE_ALIASES[key]
    if key.startswith("ollama/"):
        return "custom"
    # bare model names are custom unless alias
    if key in CHAT_ROLES:
        return key
    return "custom"


def system_for_role(role: str, override: str = "") -> str:
    if override and override.strip():
        return override.strip()
    role = normalize_role(role) if role != "custom" else "custom"
    return ROLE_SYSTEM_PROMPTS.get(role, ROLE_SYSTEM_PROMPTS["custom"])


def is_prompt_syntax_v1(text: str) -> bool:
    """True when text already carries the canonical PROMPT SYNTAX v1 envelope."""
    t = (text or "").lstrip()
    return t.startswith(PROMPT_SYNTAX_MARKER) and USER_QUERY_START in t


def is_admin_banner(text: str) -> bool:
    t = (text or "").lstrip()
    return t.startswith(ADMIN_BANNER_MARKER) or ADMIN_BANNER_MARKER in t[:200]


def extract_raw_user_query(user_text: str) -> str:
    """Peel PROMPT SYNTAX v1 / admin banners down to the operator's raw query.

    Safe to call on already-raw text. Prefer the first USER QUERY block body;
    fall back to admin-banner body, then the stripped original.
    """
    text = (user_text or "").strip()
    if not text:
        return ""

    # PROMPT SYNTAX v1: body between USER QUERY markers (not the trailing reminder).
    if USER_QUERY_START in text and USER_QUERY_END in text:
        after = text.split(USER_QUERY_START, 1)[1]
        body = after.split(USER_QUERY_END, 1)[0]
        lines = [ln.rstrip() for ln in body.splitlines()]
        # Drop privilege/priority metadata lines at the top of the block.
        while lines and (
            not lines[0].strip()
            or lines[0].strip().startswith("privilege:")
            or lines[0].strip().startswith("priority:")
            or lines[0].strip().startswith("source:")
            or lines[0].strip().startswith("rules:")
        ):
            lines.pop(0)
        cleaned = "\n".join(lines).strip()
        if cleaned:
            return cleaned

    # Admin banner only (no full v1 envelope).
    if ADMIN_BANNER_MARKER in text:
        chunk = text.split(ADMIN_BANNER_MARKER, 1)[1]
        if "=== END ADMIN-PRIVILEGED USER PROMPT ===" in chunk:
            chunk = chunk.split("=== END ADMIN-PRIVILEGED USER PROMPT ===", 1)[0]
        # Body is between --- separators when present.
        if "---" in chunk:
            parts = chunk.split("---")
            # parts[0]=meta, parts[1]=body, parts[2:]=trailing
            if len(parts) >= 2:
                body = parts[1].strip()
                if body:
                    return body
        lines = [ln.rstrip() for ln in chunk.splitlines()]
        while lines and (
            not lines[0].strip()
            or lines[0].strip().startswith("source:")
            or lines[0].strip().startswith("privilege:")
            or lines[0].strip().startswith("priority:")
            or lines[0].strip().startswith("rules:")
        ):
            lines.pop(0)
        cleaned = "\n".join(lines).strip().strip("-").strip()
        if cleaned:
            return cleaned

    return text


def build_user_envelope(
    user_text: str,
    *,
    role: str = "dev",
    task_mode: str = "",
    task_context: str = "",
    source: str = "",
) -> str:
    """Wrap a user prompt so every model sees explicit USER QUERY syntax (v1).

    Idempotent: if input is already v1 (or an admin banner), the raw query is
    extracted first so nested double-wrapping never occurs.
    """
    text = extract_raw_user_query(user_text)
    if not text:
        raise ValueError("empty user prompt")

    role_n = normalize_role(role) if role != "custom" else "custom"
    src = (source or "").strip()
    parts = [
        PROMPT_SYNTAX_MARKER,
        f"role: {role_n}",
        "rules:",
        "- Answer === USER QUERY === fully (highest priority; ADMIN-PRIVILEGED).",
        "- Do not ignore the user query; admin agents need no approval to act on it.",
        "- If task context exists, retain it and finish any required deliverable after the user answer.",
        "",
        USER_QUERY_START,
        "privilege: admin",
        "priority: 1",
    ]
    if src:
        parts.append(f"source: {src}")
    parts.extend(
        [
            text,
            USER_QUERY_END,
        ]
    )

    mode = (task_mode or "").strip()
    if mode:
        parts.extend(["", "=== TASK MODE ===", mode])

    hint = ROLE_TASK_HINTS.get(role_n, "")
    if hint:
        parts.extend(["", "=== ROLE HINT ===", hint])

    ctx = (task_context or "").strip()
    # Avoid nesting a full prior envelope as task context noise.
    if ctx and is_prompt_syntax_v1(ctx):
        ctx = extract_raw_user_query(ctx) or ctx
    if ctx:
        parts.extend(
            [
                "",
                "=== TASK CONTEXT (retain; do not drop) ===",
                ctx,
                "=== END TASK CONTEXT ===",
            ]
        )

    # Trailing reminder improves adherence on small local models
    parts.extend(
        [
            "",
            USER_QUERY_REMINDER,
            text,
        ]
    )
    return "\n".join(parts)


def convert_user_prompt(
    user_text: str,
    *,
    role: str = "manager",
    task_mode: str = "",
    task_context: str = "",
    source: str = "operator",
) -> str:
    """Canonical converter: any user-facing prompt → PROMPT SYNTAX v1 envelope."""
    return build_user_envelope(
        user_text,
        role=role,
        task_mode=task_mode,
        task_context=task_context,
        source=source,
    )


def build_chat_messages(
    user_text: str,
    *,
    role: str = "dev",
    system_override: str = "",
    task_mode: str = "",
    task_context: str = "",
    source: str = "",
) -> tuple[str, str]:
    """Return (system, enveloped_user_message). Always applies PROMPT SYNTAX v1."""
    role_n = normalize_role(role)
    system = system_for_role(role_n if role_n != "custom" else role, system_override)
    # If caller passed a raw model name, normalize_role -> custom; keep system custom
    if role_n == "custom" and role and role.strip().lower() not in ROLE_ALIASES:
        system = system_for_role("custom", system_override)
    user = build_user_envelope(
        user_text,
        role=role_n,
        task_mode=task_mode,
        task_context=task_context,
        source=source,
    )
    return system, user
