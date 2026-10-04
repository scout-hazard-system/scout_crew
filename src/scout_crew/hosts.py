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

"""Where things live, for a crew that runs across several machines.

Single source of truth for host/path resolution. Nothing here assumes the
crew, the map server, the blackboard hub and the model engines share a disk
or a home directory: services are reached by URL over the Scout mesh, and
local files resolve under explicit, overridable roots.

Environment (all optional):
  SCOUT_MESH_HUB_ADDRESS   mesh hub (map server :18080, blackboard :8765,
                           hub Ollama :11434)            default 10.66.0.1
  SCOUT_MESH_CIDR          mesh range                    default 10.66.0.0/16
  SCOUT_PEER_MESH_IP       peer with the large-model Ollama
  SCOUT_PEER_OLLAMA_PORT   that peer's Ollama port       default 11434
  SCOUT_DATA_ROOT          local copy of vlm_text_map_shards*/ and
                           stack/config/ catalogs        default ~/Desktop
  SCOUT_STATE_DIR          per-host scratch/state        default
                           $XDG_STATE_HOME/scout or ~/.local/state/scout
  SCOUT_OUTPUT_DIR         crew artifacts                default <project>/output
  SCOUT_ALLOWED_LLM_HOSTS  extra comma-separated hosts the local-only guard
                           accepts (besides loopback and the mesh)
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

MESH_HUB_DEFAULT = "10.66.0.1"
MESH_CIDR_DEFAULT = "10.66.0.0/16"


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def mesh_hub() -> str:
    return _env("SCOUT_MESH_HUB_ADDRESS") or MESH_HUB_DEFAULT


def mesh_cidr() -> str:
    return _env("SCOUT_MESH_CIDR") or MESH_CIDR_DEFAULT


def hub_url(port: int) -> str:
    return f"http://{mesh_hub()}:{port}"


def blackboard_url() -> str:
    return _env("SCOUT_BLACKBOARD_URL").rstrip("/") or hub_url(8765)


def map_server_url() -> str:
    for key in ("SCOUT_MAP_BASE_URL", "SCOUT_BACKEND_URL"):
        value = _env(key).rstrip("/")
        if value:
            return value
    return hub_url(18080)


def peer_ollama_url() -> str:
    """Native Ollama URL of the large-model peer ('' when not configured).

    Prefers an explicit SCOUT_PEER_OLLAMA_HOST, then the OpenAI-style
    SCOUT_PEER_OLLAMA_OPENAI (minus /v1), then SCOUT_PEER_MESH_IP plus port.
    """
    explicit = _env("SCOUT_PEER_OLLAMA_HOST").rstrip("/")
    if explicit:
        return explicit
    openai = _env("SCOUT_PEER_OLLAMA_OPENAI").rstrip("/")
    if openai:
        return openai[: -len("/v1")] if openai.endswith("/v1") else openai
    peer = _env("SCOUT_PEER_MESH_IP")
    if not peer:
        return ""
    return f"http://{peer}:{_env('SCOUT_PEER_OLLAMA_PORT') or '11434'}"


def data_root() -> Path:
    return Path(_env("SCOUT_DATA_ROOT") or (Path.home() / "Desktop")).expanduser()


def state_dir() -> Path:
    explicit = _env("SCOUT_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    xdg = _env("XDG_STATE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "state"
    return base / "scout"


def project_root() -> Path:
    """The crew install/checkout (holds pyproject.toml, bin/, output/)."""
    return Path(__file__).resolve().parents[2]


def output_dir() -> Path:
    """Crew artifacts (briefs, az_manager_status.json). The GUI and CrewAI's
    relative task outputs use <project>/output, so that is the default."""
    explicit = _env("SCOUT_OUTPUT_DIR")
    return Path(explicit).expanduser() if explicit else project_root() / "output"


def _host_of(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
    except ValueError:
        return None
    return parsed.hostname


def is_local_or_mesh(url: str) -> bool:
    """True for loopback, the Scout mesh, or an explicitly allowed host.

    Port-agnostic on purpose: mesh engines listen on 11434 (Ollama),
    11435 (Ollama behind a local proxy) and 8000 (vLLM).
    """
    host = _host_of(url)
    if not host:
        return False
    if host in {"localhost"}:
        return True
    allowed = {h.strip().lower() for h in _env("SCOUT_ALLOWED_LLM_HOSTS").split(",") if h.strip()}
    if host.lower() in allowed:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    try:
        return ip in ipaddress.ip_network(mesh_cidr(), strict=False)
    except ValueError:
        return False


if __name__ == "__main__":  # used by the bin/ launchers' local-only guard
    import sys

    sys.exit(0 if all(is_local_or_mesh(u) for u in sys.argv[1:]) else 1)
