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

"""CrewAI tools for the categorized multi-machine Scout blackboard."""

from __future__ import annotations

import json
from typing import List, Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from scout_crew.blackboard.client import BlackboardClient


def _client() -> BlackboardClient:
    return BlackboardClient()


class _WriteIn(BaseModel):
    category: str = Field(..., description="pipeline | dev_debug")
    title: str = Field(..., description="Short title")
    body: str = Field(..., description="Entry body / facts / notes")
    kind: str = Field(
        default="raw",
        description="raw | summary | rewrite. Manager must use summary/rewrite on pipeline.",
    )
    tags: str = Field(
        default="",
        description="Comma-separated tags, e.g. alert,az,i10",
    )
    supersede_id: str = Field(
        default="",
        description="Optional prior entry id this summary/rewrite replaces",
    )


class _ReadIn(BaseModel):
    category: str = Field(..., description="pipeline | dev_debug")
    limit: int = Field(default=12, description="Max entries (1-50)")
    kind: str = Field(default="", description="Optional filter: raw|summary|rewrite")
    query: str = Field(default="", description="Optional substring filter")
    tag: str = Field(default="", description="Optional tag filter")


class _SnapshotIn(BaseModel):
    limit_per_category: int = Field(default=10, description="Max entries per category")


def _tags_list(tags: str) -> List[str]:
    return [t.strip() for t in (tags or "").split(",") if t.strip()]


class BlackboardWriteTool(BaseTool):
    name: str = "blackboard_write"
    description: str = (
        "Write an entry to the shared multi-machine Scout blackboard. "
        "Specialists write category=pipeline kind=raw. "
        "Manager writes category=pipeline kind=summary|rewrite (succinct). "
        "Dev writes category=dev_debug only. Hermes must NOT write."
    )
    args_schema: Type[BaseModel] = _WriteIn
    role: str = "operator"

    def _run(
        self,
        category: str,
        title: str,
        body: str,
        kind: str = "raw",
        tags: str = "",
        supersede_id: str = "",
    ) -> str:
        try:
            entry = _client().write(
                category=category,
                role=self.role,
                title=title,
                body=body,
                kind=kind or "raw",
                tags=_tags_list(tags),
                supersede_id=supersede_id or None,
                meta={"source": "crewai_tool"},
            )
            return json.dumps({"ok": True, "entry": entry}, indent=2)
        except Exception as e:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(e)})


class BlackboardReadTool(BaseTool):
    name: str = "blackboard_read"
    description: str = (
        "Read recent entries from one blackboard category (pipeline or dev_debug). "
        "All roles may read permitted categories. Hermes is read-only overall."
    )
    args_schema: Type[BaseModel] = _ReadIn
    role: str = "operator"

    def _run(
        self,
        category: str,
        limit: int = 12,
        kind: str = "",
        query: str = "",
        tag: str = "",
    ) -> str:
        try:
            client = _client()
            entries = client.read(
                category=category,
                role=self.role,
                limit=min(max(int(limit or 12), 1), 50),
                kind=kind or None,
                query=query or None,
                tag=tag or None,
            )
            return client.format_entries(entries)
        except Exception as e:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(e)})


class BlackboardSnapshotTool(BaseTool):
    name: str = "blackboard_snapshot"
    description: str = (
        "Snapshot all blackboard categories you can read (pipeline + dev_debug if allowed). "
        "Use before synthesis or long-context reasoning."
    )
    args_schema: Type[BaseModel] = _SnapshotIn
    role: str = "operator"

    def _run(self, limit_per_category: int = 10) -> str:
        try:
            client = _client()
            snap = client.snapshot(
                role=self.role,
                limit_per_category=min(max(int(limit_per_category or 10), 1), 30),
            )
            parts = []
            for cat, entries in snap.items():
                parts.append(f"## {cat} ({len(entries)})")
                parts.append(client.format_entries(entries))
            return "\n".join(parts) if parts else "(empty blackboard snapshot)"
        except Exception as e:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(e)})


def tools_for_role(role: str) -> list:
    """Return blackboard tool instances bound to a logical role."""
    r = (role or "operator").strip().lower()
    # hermes: read-only
    if r in {"hermes", "scout-hermes", "scout-hermes-hc", "scout-hermes-hc1.0.0"}:
        return [
            BlackboardReadTool(role="hermes"),
            BlackboardSnapshotTool(role="hermes"),
        ]
    if r in {"manager", "local_manager", "mgr", "admin"}:
        return [
            BlackboardReadTool(role="manager"),
            BlackboardSnapshotTool(role="manager"),
            BlackboardWriteTool(role="manager"),
        ]
    if r in {"dev", "dev_specialist", "scout-dev"}:
        return [
            BlackboardReadTool(role="dev"),
            BlackboardSnapshotTool(role="dev"),
            BlackboardWriteTool(role="dev"),
        ]
    # specialists / core writers
    specialist = r.replace("_specialist", "")
    if specialist in {"alert", "intel", "vet", "rank", "core"}:
        return [
            BlackboardReadTool(role=specialist),
            BlackboardSnapshotTool(role=specialist),
            BlackboardWriteTool(role=specialist),
        ]
    # default operator: full read + no write unless pipeline writer
    return [
        BlackboardReadTool(role="operator"),
        BlackboardSnapshotTool(role="operator"),
    ]
