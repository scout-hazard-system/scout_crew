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

"""Blackboard client: local SQLite or remote HTTP multi-machine backend."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from scout_crew.blackboard.store import BlackboardStore, Entry


class BlackboardClient:
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        db_path: Optional[Path] = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("SCOUT_BLACKBOARD_URL", "")).rstrip("/")
        self.timeout = timeout
        self._local: Optional[BlackboardStore] = None
        if not self.base_url:
            self._local = BlackboardStore(db_path=db_path)

    @property
    def mode(self) -> str:
        return "remote" if self.base_url else "local"

    def _http(self, method: str, path: str, payload: Optional[dict] = None) -> Any:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"blackboard HTTP {e.code}: {detail}") from e

    def write(self, **kwargs: Any) -> Dict[str, Any]:
        if self._local:
            return self._local.write(**kwargs).to_dict()
        return self._http("POST", "/v1/write", kwargs)

    def read(self, **kwargs: Any) -> List[Dict[str, Any]]:
        if self._local:
            return [e.to_dict() for e in self._local.read(**kwargs)]
        q = urllib.parse.urlencode({k: v for k, v in kwargs.items() if v is not None})
        return self._http("GET", f"/v1/read?{q}")

    def snapshot(self, **kwargs: Any) -> Dict[str, Any]:
        if self._local:
            return self._local.snapshot(**kwargs)
        q = urllib.parse.urlencode({k: v for k, v in kwargs.items() if v is not None})
        return self._http("GET", f"/v1/snapshot?{q}")

    def stats(self) -> Dict[str, Any]:
        if self._local:
            return self._local.stats()
        return self._http("GET", "/v1/stats")

    def format_entries(self, entries: List[Dict[str, Any]], *, max_body: int = 800) -> str:
        if not entries:
            return "(no blackboard entries)"
        lines = []
        for e in entries:
            tags = ",".join(e.get("tags") or [])
            body = (e.get("body") or "").strip()
            if len(body) > max_body:
                body = body[: max_body - 3] + "..."
            lines.append(
                f"- [{e.get('category')}/{e.get('kind')}] id={e.get('id')} "
                f"role={e.get('role')} host={e.get('host')} title={e.get('title')}\n"
                f"  tags={tags}\n  {body}"
            )
        return "\n".join(lines)
