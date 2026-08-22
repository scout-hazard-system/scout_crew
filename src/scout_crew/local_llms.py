"""Local-only LLM wiring for CrewAI via Ollama.

All models are served by the local Ollama daemon at 127.0.0.1:11434.
No cloud provider keys or external token usage.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Set

import requests
from crewai import LLM

OLLAMA_HOST = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_TAGS_URL = f"{OLLAMA_HOST}/api/tags"
OLLAMA_OPENAI_BASE = os.getenv("OPENAI_BASE_URL", f"{OLLAMA_HOST}/v1")

# Role -> preferred Ollama model name (without provider prefix)
ROLE_MODEL_PREFS: Dict[str, List[str]] = {
    "manager": ["llama3.1", "llama3.1:latest"],
    "core": ["scout-core1.0.5", "scout-core1.0.8", "scout-core1.0.7", "scout-core", "llama3.1"],
    "vet": ["scout-vet1.0.6", "scout-vet1.0.8", "scout-vet1.0.7", "scout-vet", "llama3.1"],
    "alert": ["scout-alert", "scout-vet1.0.6", "scout-vet1.0.8", "llama3.1"],
    "intel": ["scout-intel", "scout-vet1.0.6", "scout-vet1.0.8", "llama3.1"],
    "rank": ["scout-rank", "llama3.1"],
    "dev": ["scout-dev", "scout-core1.0.5", "scout-core", "llama3.1"],
    "base": ["llama3.1", "llama3.1:latest"],
}

ENV_OVERRIDES = {
    "manager": "OLLAMA_MODEL_MANAGER",
    "core": "OLLAMA_MODEL_CORE",
    "vet": "OLLAMA_MODEL_VET",
    "alert": "OLLAMA_MODEL_ALERT",
    "intel": "OLLAMA_MODEL_INTEL",
    "rank": "OLLAMA_MODEL_RANK",
    "dev": "OLLAMA_MODEL_DEV",
    "base": "OLLAMA_MODEL_BASE",
}


def _strip_provider(name: str) -> str:
    name = name.strip()
    if name.startswith("ollama/"):
        return name[len("ollama/") :]
    return name


def _with_provider(name: str) -> str:
    name = name.strip()
    if "/" in name:
        return name
    return f"ollama/{name}"


@lru_cache(maxsize=1)
def installed_ollama_models(force_refresh: bool = False) -> Set[str]:
    """Return installed Ollama model names (with and without :latest)."""
    if force_refresh:
        installed_ollama_models.cache_clear()
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=3.0)
        response.raise_for_status()
        names: Set[str] = set()
        for item in response.json().get("models", []):
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            names.add(name)
            if name.endswith(":latest"):
                names.add(name[: -len(":latest")])
            else:
                names.add(f"{name}:latest")
        return names
    except Exception as exc:  # noqa: BLE001 - surface later via status
        raise RuntimeError(
            f"Ollama is unreachable at {OLLAMA_TAGS_URL}. "
            "Start it with `ollama serve` before running the crew."
        ) from exc


def resolve_role_model(role: str, installed: Optional[Set[str]] = None) -> str:
    """Pick the best installed model for a role. Returns bare ollama model name."""
    role = role.lower().strip()
    env_key = ENV_OVERRIDES.get(role)
    candidates: List[str] = []
    if env_key:
        override = os.getenv(env_key, "").strip()
        if override:
            candidates.append(_strip_provider(override))

    candidates.extend(ROLE_MODEL_PREFS.get(role, ROLE_MODEL_PREFS["base"]))

    if installed is None:
        try:
            installed = installed_ollama_models()
        except RuntimeError:
            # Prefer configured name so the LLM call fails with a clear model error.
            return candidates[0] if candidates else "llama3.1"

    for candidate in candidates:
        bare = _strip_provider(candidate)
        if bare in installed or f"{bare}:latest" in installed:
            return bare.split(":")[0] if bare.endswith(":latest") else bare
        # Also accept exact tag matches already in installed set
        if bare in installed:
            return bare

    # Last resort: any installed model, else first candidate
    if installed:
        # Prefer llama3.1 if present
        for preferred in ("llama3.1", "llama3.1:latest"):
            if preferred in installed:
                return "llama3.1"
        sample = next(iter(installed))
        return sample.split(":")[0]
    return candidates[0] if candidates else "llama3.1"


def make_llm(role: str, temperature: float = 0.2, max_tokens: int = 2048) -> LLM:
    """Build a CrewAI LLM bound to the local Ollama OpenAI-compatible API."""
    model_name = resolve_role_model(role)
    # Ensure dummy local key is present for OpenAI-compatible clients
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    os.environ.setdefault("OPENAI_API_BASE", OLLAMA_OPENAI_BASE)
    os.environ.setdefault("OPENAI_BASE_URL", OLLAMA_OPENAI_BASE)

    return LLM(
        model=_with_provider(model_name),
        base_url=OLLAMA_OPENAI_BASE,
        api_key=os.getenv("OPENAI_API_KEY", "ollama"),
        temperature=temperature,
        max_tokens=max_tokens,
    )


def model_roster() -> Dict[str, str]:
    """Map each crew role to the resolved local model name."""
    try:
        installed = installed_ollama_models(force_refresh=True)
    except RuntimeError:
        installed = set()
    return {role: resolve_role_model(role, installed) for role in ROLE_MODEL_PREFS}


def status() -> dict:
    """Diagnostics for local manager / model availability."""
    try:
        installed = sorted(installed_ollama_models(force_refresh=True))
        ollama_up = True
        error = None
    except RuntimeError as exc:
        installed = []
        ollama_up = False
        error = str(exc)

    roster = {role: resolve_role_model(role, set(installed) if installed else None) for role in ROLE_MODEL_PREFS}
    return {
        "ollama_up": ollama_up,
        "ollama_host": OLLAMA_HOST,
        "openai_compatible_base": OLLAMA_OPENAI_BASE,
        "external_token_usage": False,
        "installed_models": installed,
        "role_assignments": roster,
        "error": error,
    }


def assert_local_only() -> None:
    """Fail fast if env looks configured for a cloud LLM provider."""
    blocked_keys = [
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "TOGETHER_API_KEY",
        "OPENROUTER_API_KEY",
        "COHERE_API_KEY",
    ]
    present = [k for k in blocked_keys if os.getenv(k)]
    # OPENAI_API_KEY may be the dummy "ollama" value; real cloud keys are long.
    openai_key = os.getenv("OPENAI_API_KEY", "")
    base = (os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE") or "").lower()
    if openai_key and openai_key not in {"ollama", "local", "not-needed", "na"} and "11434" not in base and "localhost" not in base and "127.0.0.1" not in base:
        present.append("OPENAI_API_KEY (non-local base URL)")
    if present:
        raise RuntimeError(
            "Refusing to start: cloud LLM credentials detected while local-only mode is required: "
            + ", ".join(present)
        )