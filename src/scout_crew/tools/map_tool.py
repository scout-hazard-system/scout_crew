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

"""Read-only CrewAI tools for the Scout map server.

The map server (hub, :18080) is the route/geo source of truth. These tools are
GET-only for every role: agents query live map state but never write geometry to
the blackboard or elsewhere. Resolution order:

    SCOUT_MAP_BASE_URL
        -> SCOUT_BACKEND_URL
        -> http://{SCOUT_MESH_HUB_ADDRESS}:18080   (default hub 10.66.2.3)
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def map_base_url() -> str:
    """Resolve the map server base URL (no trailing slash)."""
    for key in ("SCOUT_MAP_BASE_URL", "SCOUT_BACKEND_URL"):
        value = (os.getenv(key) or "").strip().rstrip("/")
        if value:
            return value
    hub = (os.getenv("SCOUT_MESH_HUB_ADDRESS") or "").strip() or "10.66.2.3"
    return f"http://{hub}:18080"


def _auth_headers() -> Dict[str, str]:
    """Device-bound subscription credentials for the map server paywall.

    SCOUT_SUBSCRIPTION_TOKEN is issued per device by the backend admin
    (/api/admin/subscription/issue); mesh transport alone is not entitlement.
    """
    headers: Dict[str, str] = {}
    token = (os.getenv("SCOUT_SUBSCRIPTION_TOKEN") or "").strip()
    if token:
        header = (os.getenv("SCOUT_SUBSCRIPTION_HEADER") or "X-Scout-Subscription").strip()
        headers[header] = token
        device = (os.getenv("SCOUT_DEVICE_ID") or "").strip()
        if device:
            headers["X-Scout-Device-Id"] = device
    return headers


def _get(path: str, *, timeout: float = 10.0, max_body: int = 4000) -> Dict[str, Any]:
    """Read-only GET against the map server; always returns a JSON dict."""
    url = f"{map_base_url()}{path}"
    try:
        req = urllib.request.Request(url, headers=_auth_headers())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return {
            "ok": True,
            "endpoint": url,
            "status_code": getattr(resp, "status", 200),
            "body": body[:max_body],
            "error": None,
        }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:max_body]
        return {
            "ok": False,
            "endpoint": url,
            "status_code": exc.code,
            "body": detail,
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "endpoint": url,
            "status_code": None,
            "body": "",
            "error": str(exc),
        }


class _EmptyIn(BaseModel):
    pass


class _ShardIn(BaseModel):
    state: str = Field(default="AZ", description="State abbreviation, e.g. AZ")
    active_only: bool = Field(default=True, description="Only active markers (status=1)")


class _RouteWeatherIn(BaseModel):
    via: str = Field(
        default="",
        description="Optional comma-separated via points or route id for weather lookup",
    )


class MapHealthTool(BaseTool):
    name: str = "map_health"
    description: str = (
        "Read-only: check the Scout map server (hub) health endpoint /api/health. "
        "Use to confirm the map backend is up before reading any map shards."
    )
    args_schema: Type[BaseModel] = _EmptyIn

    def _run(self) -> str:
        return json.dumps(_get("/api/health"), indent=2)


class MapStatusTool(BaseTool):
    name: str = "map_status"
    description: str = (
        "Read-only: query map server coverage status (/api/map/status) — current "
        "state shards, marker coverage, and rail/route layers served by the hub."
    )
    args_schema: Type[BaseModel] = _EmptyIn

    def _run(self) -> str:
        return json.dumps(_get("/api/map/status"), indent=2)


class MapShardTool(BaseTool):
    name: str = "map_shard"
    description: str = (
        "Read-only: fetch a map data shard from the hub map server "
        "(/api/map/shard). Supply state (e.g. AZ) for the shard; active_only "
        "returns current marker coverage. Never submit geometry back to the "
        "blackboard."
    )
    args_schema: Type[BaseModel] = _ShardIn

    def _run(self, state: str = "AZ", active_only: bool = True) -> str:
        query = urllib.parse.urlencode(
            {"state": state or "AZ", **({"status": 1} if active_only else {})}
        )
        return json.dumps(_get(f"/api/map/shard?{query}"), indent=2)


class MapRouteWeatherTool(BaseTool):
    name: str = "map_route_weather"
    description: str = (
        "Read-only: query route/weather layer from the map server "
        "(/api/route/weather). GET-only; returns observed conditions along the "
        "requested route from the hub's route server."
    )
    args_schema: Type[BaseModel] = _RouteWeatherIn

    def _run(self, via: str = "") -> str:
        query = urllib.parse.urlencode({"via": via}) if via else ""
        return json.dumps(_get(f"/api/route/weather?{query}" if query else "/api/route/weather"), indent=2)


def map_tools_for_role(_role: str) -> list:
    """Read-only map tools for every role (peer mesh + harness)."""
    return [MapHealthTool(), MapStatusTool(), MapShardTool(), MapRouteWeatherTool()]