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

"""Local/mesh LLM wiring for CrewAI via Ollama.

Default: all roles hit OLLAMA_BASE_URL (this machine).
Optional split routing (Tailscale mesh):
  OLLAMA_HOST_HERMES / OLLAMA_HOST_MANAGER  -> Windows (scout-hermes-hc)
  OLLAMA_HOST_ALERT / INTEL / VET / RANK / CORE / DEV -> Linux specialists

No cloud provider keys or external token usage.
Default weight lineage: Qwen3 (not Llama/Meta).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import requests
from crewai import LLM

# Default Ollama on this machine (specialists / training host).
OLLAMA_HOST = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_TAGS_URL = f"{OLLAMA_HOST}/api/tags"
OLLAMA_OPENAI_BASE = os.getenv("OPENAI_BASE_URL", f"{OLLAMA_HOST}/v1").rstrip("/")

# Role -> preferred Ollama model name (without provider prefix)
ROLE_MODEL_PREFS: Dict[str, List[str]] = {
    # Reasoning roles share the thinking-capable unified Hermes brain (Qwen3 lineage).
    # Fallbacks stay on qwen3:8b — do not fall back to Llama (Meta license).
    "manager": [
        "scout-hermes-hc1.1.0",
        "scout-hermes-hc1.0.0",
        "scout-hermes-hc1.0.0-64k",
        "scout-hermes-hc1.1.0-64k",
        "qwen3:8b",
    ],
    "core": [
        "scout-core1.0.5",
        "scout-core",
        "scout-hermes-hc1.1.0",
        "scout-hermes-hc1.0.0",
        "qwen3:8b",
    ],
    "dev": [
        "scout-dev",
        "scout-core1.0.5",
        "scout-hermes-hc1.1.0",
        "scout-hermes-hc1.0.0",
        "qwen3:8b",
    ],
    # Specialists: narrow contracts on Qwen3 weights (same base as hermes-hc).
    "vet": ["scout-vet1.0.6", "scout-vet1.0.8", "scout-vet1.0.7", "scout-vet", "qwen3:8b"],
    "alert": ["scout-alert", "scout-vet1.0.6", "scout-vet1.0.8", "qwen3:8b"],
    "intel": ["scout-intel", "scout-vet1.0.6", "scout-vet1.0.8", "qwen3:8b"],
    "rank": ["scout-rank", "qwen3:8b"],
    "base": ["qwen3:8b", "qwen3:8b:latest"],
    # Optional explicit hermes role
    "hermes": [
        "scout-hermes-hc1.1.0",
        "scout-hermes-hc1.0.0",
        "scout-hermes-hc1.0.0-64k",
        "scout-hermes-hc1.1.0-64k",
        "qwen3:8b",
    ],
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
    "hermes": "OLLAMA_MODEL_HERMES",
}

# Per-role Ollama base URL overrides (no /v1). Empty -> OLLAMA_HOST.
# Convenience: SCOUT_PEER_OLLAMA_OPENAI=http://WINDOWS:11434/v1 also feeds hermes/manager
# when OLLAMA_HOST_HERMES is unset.
ENV_HOST_OVERRIDES = {
    "manager": "OLLAMA_HOST_MANAGER",
    "core": "OLLAMA_HOST_CORE",
    "vet": "OLLAMA_HOST_VET",
    "alert": "OLLAMA_HOST_ALERT",
    "intel": "OLLAMA_HOST_INTEL",
    "rank": "OLLAMA_HOST_RANK",
    "dev": "OLLAMA_HOST_DEV",
    "base": "OLLAMA_HOST_BASE",
    "hermes": "OLLAMA_HOST_HERMES",
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


def _normalize_ollama_host(url: str) -> str:
    """Accept http://host:11434 or .../v1 and return scheme://host:port (no path)."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _openai_base_for_host(host: str) -> str:
    host = host.rstrip("/")
    if host.endswith("/v1"):
        return host
    return f"{host}/v1"


def resolve_role_host(role: str) -> str:
    """Ollama daemon base URL for a role (no /v1)."""
    role = role.lower().strip()
    env_key = ENV_HOST_OVERRIDES.get(role)
    if env_key:
        override = os.getenv(env_key, "").strip()
        if override:
            return _normalize_ollama_host(override)

    # Mesh convenience: peer Windows OpenAI URL drives hermes + manager when set.
    if role in {"hermes", "manager"}:
        peer = os.getenv("SCOUT_PEER_OLLAMA_OPENAI", "").strip()
        if peer:
            return _normalize_ollama_host(peer)
        peer_host = os.getenv("SCOUT_PEER_OLLAMA_HOST", "").strip()
        if peer_host:
            return _normalize_ollama_host(peer_host)

    return OLLAMA_HOST


@lru_cache(maxsize=16)
def installed_ollama_models_at(host: str, force_refresh: bool = False) -> Set[str]:
    """Return installed Ollama model names on a specific host."""
    host = _normalize_ollama_host(host) or OLLAMA_HOST
    if force_refresh:
        installed_ollama_models_at.cache_clear()
    tags_url = f"{host}/api/tags"
    try:
        response = requests.get(tags_url, timeout=3.0)
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
            f"Ollama is unreachable at {tags_url}. "
            "Start it with `ollama serve` (and bind 0.0.0.0 for mesh) before running the crew."
        ) from exc


@lru_cache(maxsize=1)
def installed_ollama_models(force_refresh: bool = False) -> Set[str]:
    """Return installed Ollama model names on the default host."""
    if force_refresh:
        installed_ollama_models.cache_clear()
        installed_ollama_models_at.cache_clear()
    return installed_ollama_models_at(OLLAMA_HOST, force_refresh=False)


def resolve_role_model(
    role: str,
    installed: Optional[Set[str]] = None,
    host: Optional[str] = None,
) -> str:
    """Pick the best installed model for a role on its host. Returns bare ollama model name."""
    role = role.lower().strip()
    env_key = ENV_OVERRIDES.get(role)
    candidates: List[str] = []
    if env_key:
        override = os.getenv(env_key, "").strip()
        if override:
            candidates.append(_strip_provider(override))

    candidates.extend(ROLE_MODEL_PREFS.get(role, ROLE_MODEL_PREFS["base"]))

    role_host = host or resolve_role_host(role)
    if installed is None:
        try:
            installed = installed_ollama_models_at(role_host)
        except RuntimeError:
            # Prefer configured name so the LLM call fails with a clear model error.
            return candidates[0] if candidates else "qwen3:8b"

    for candidate in candidates:
        bare = _strip_provider(candidate)
        if bare in installed or f"{bare}:latest" in installed:
            return bare.split(":")[0] if bare.endswith(":latest") else bare
        if bare in installed:
            return bare

    # Last resort: any installed Qwen/Scout model, else first candidate
    if installed:
        for preferred in (
            "qwen3:8b",
            "qwen3:8b:latest",
            "scout-hermes-hc1.1.0",
            "scout-hermes-hc1.0.0",
        ):
            if preferred in installed:
                return preferred.split(":")[0] if preferred.endswith(":latest") else preferred
        for name in sorted(installed):
            bare = name.split(":")[0]
            if bare.startswith("scout-") or bare.startswith("qwen"):
                return bare
        sample = next(iter(installed))
        return sample.split(":")[0]
    return candidates[0] if candidates else "qwen3:8b"


def make_llm(role: str, temperature: float = 0.2, max_tokens: int = 2048) -> LLM:
    """Build a CrewAI LLM bound to the role's Ollama OpenAI-compatible API."""
    host = resolve_role_host(role)
    model_name = resolve_role_model(role, host=host)
    openai_base = _openai_base_for_host(host)

    # Ensure dummy local key is present for OpenAI-compatible clients
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    # Keep global defaults on the primary host; per-role base_url is set on LLM.
    os.environ.setdefault("OPENAI_API_BASE", OLLAMA_OPENAI_BASE)
    os.environ.setdefault("OPENAI_BASE_URL", OLLAMA_OPENAI_BASE)

    return LLM(
        model=_with_provider(model_name),
        base_url=openai_base,
        api_key=os.getenv("OPENAI_API_KEY", "ollama"),
        temperature=temperature,
        max_tokens=max_tokens,
    )


def model_roster() -> Dict[str, str]:
    """Map each crew role to the resolved model name (host-aware)."""
    out: Dict[str, str] = {}
    for role in ROLE_MODEL_PREFS:
        host = resolve_role_host(role)
        try:
            installed = installed_ollama_models_at(host, force_refresh=True)
        except RuntimeError:
            installed = set()
        out[role] = resolve_role_model(role, installed, host=host)
    return out


def role_endpoints() -> Dict[str, Dict[str, str]]:
    """Map each role to {host, model, openai_base}."""
    roster = {}
    for role in ROLE_MODEL_PREFS:
        host = resolve_role_host(role)
        try:
            installed = installed_ollama_models_at(host)
        except RuntimeError:
            installed = set()
        model = resolve_role_model(role, installed, host=host)
        roster[role] = {
            "host": host,
            "model": model,
            "openai_base": _openai_base_for_host(host),
        }
    return roster


def status() -> dict:
    """Diagnostics for local/mesh manager / model availability."""
    hosts_needed = {resolve_role_host(r) for r in ROLE_MODEL_PREFS}
    host_status: Dict[str, dict] = {}
    for host in sorted(hosts_needed):
        try:
            installed = sorted(installed_ollama_models_at(host, force_refresh=True))
            host_status[host] = {"up": True, "models": installed, "error": None}
        except RuntimeError as exc:
            host_status[host] = {"up": False, "models": [], "error": str(exc)}

    default_up = bool(host_status.get(OLLAMA_HOST, {}).get("up"))
    default_err = host_status.get(OLLAMA_HOST, {}).get("error")
    default_installed = host_status.get(OLLAMA_HOST, {}).get("models") or []

    endpoints = role_endpoints()
    roster = {role: info["model"] for role, info in endpoints.items()}

    leftover_llama = sorted(
        {
            m
            for models in (h.get("models") or [] for h in host_status.values())
            for m in models
            if "llama" in str(m).lower()
        }
    )
    role_uses_llama = {
        role: model
        for role, model in roster.items()
        if "llama" in str(model).lower()
    }

    return {
        "ollama_up": default_up,
        "ollama_host": OLLAMA_HOST,
        "openai_compatible_base": OLLAMA_OPENAI_BASE,
        "external_token_usage": False,
        "weight_lineage": "qwen3",
        "installed_models": default_installed,
        "hosts": host_status,
        "role_endpoints": endpoints,
        "role_assignments": roster,
        "role_uses_llama": role_uses_llama,
        "leftover_llama_installs": leftover_llama,
        "error": default_err,
    }


def assert_local_only() -> None:
    """Fail fast if env looks configured for a cloud LLM provider.

    Tailscale / LAN Ollama peers (private IPs, :11434) are allowed.
    """
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
    openai_key = os.getenv("OPENAI_API_KEY", "")

    def _looks_private_or_local(url: str) -> bool:
        u = (url or "").lower()
        if not u:
            return True
        if "11434" in u:
            return True
        if any(x in u for x in ("localhost", "127.0.0.1", "0.0.0.0", ".ts.net")):
            return True
        # Tailscale CGNAT 100.64.0.0/10 and common RFC1918
        if "://100." in u or "://10." in u or "://192.168." in u or "://172." in u:
            return True
        return False

    bases = [
        os.getenv("OPENAI_BASE_URL") or "",
        os.getenv("OPENAI_API_BASE") or "",
        os.getenv("SCOUT_PEER_OLLAMA_OPENAI") or "",
        os.getenv("SCOUT_PEER_OLLAMA_HOST") or "",
    ]
    bases.extend(os.getenv(v, "") for v in ENV_HOST_OVERRIDES.values())

    if openai_key and openai_key not in {"ollama", "local", "not-needed", "na"}:
        if not all(_looks_private_or_local(b) for b in bases if b):
            present.append("OPENAI_API_KEY (non-local base URL)")

    for b in bases:
        if b and not _looks_private_or_local(b):
            present.append(f"non-local Ollama URL: {b}")

    if present:
        raise RuntimeError(
            "Refusing to start: cloud LLM credentials or non-mesh URLs detected "
            "while local/mesh-only mode is required: " + ", ".join(present)
        )
