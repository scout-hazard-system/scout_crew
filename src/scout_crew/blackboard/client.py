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

"""Blackboard client: local SQLite or remote HTTP multi-machine backend.

When SCOUT_BLACKBOARD_TOKEN is set, remote requests carry a category-scoped
bearer token minted via POST /v1/keys/authorize (device) or /v1/keys/issue
(manager/CLI). Local mode mints local-only tokens against the configured secret.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from scout_crew.blackboard import auth
from scout_crew.blackboard.store import BlackboardStore, Entry


class BlackboardClient:
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        db_path: Optional[Path] = None,
        timeout: float = 15.0,
        memory: bool = False,
        token: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("SCOUT_BLACKBOARD_URL", "")).rstrip("/")
        self.timeout = timeout
        self._explicit_token = token or ""
        self.token = token or os.getenv("SCOUT_BLACKBOARD_TOKEN", "") or ""
        self._local: Optional[BlackboardStore] = None
        if not self.base_url:
            self._local = BlackboardStore(db_path=db_path, memory=memory)

    @property
    def mode(self) -> str:
        return "remote" if self.base_url else "local"

    def _token_for(self, role: Optional[str]) -> str:
        """Per-role token (SCOUT_BLACKBOARD_TOKEN_<ROLE>) so each agent writes
        with its own role-bound credential; generic token as fallback."""
        if self._explicit_token:
            return self._explicit_token
        if role:
            per_role = os.getenv(f"SCOUT_BLACKBOARD_TOKEN_{str(role).strip().upper()}", "").strip()
            if per_role:
                return per_role
        return self.token

    def _http(self, method: str, path: str, payload: Optional[dict] = None, *, headers: Optional[Dict[str, str]] = None, role: Optional[str] = None) -> Any:
        url = f"{self.base_url}{path}"
        data = None
        req_headers = {"Accept": "application/json"}
        token = self._token_for(role)
        if token:
            req_headers["Authorization"] = f"Bearer {token}"
        if headers:
            req_headers.update(headers)
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
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
        return self._http("POST", "/v1/write", kwargs, role=kwargs.get("role"))

    def read(self, **kwargs: Any) -> List[Dict[str, Any]]:
        if self._local:
            return [e.to_dict() for e in self._local.read(**kwargs)]
        q = urllib.parse.urlencode({k: v for k, v in kwargs.items() if v is not None})
        return self._http("GET", f"/v1/read?{q}", role=kwargs.get("role"))

    def snapshot(self, **kwargs: Any) -> Dict[str, Any]:
        if self._local:
            return self._local.snapshot(**kwargs)
        q = urllib.parse.urlencode({k: v for k, v in kwargs.items() if v is not None})
        return self._http("GET", f"/v1/snapshot?{q}", role=kwargs.get("role"))

    def stats(self) -> Dict[str, Any]:
        if self._local:
            return self._local.stats()
        return self._http("GET", "/v1/stats")

    # ---- key authorization -------------------------------------------------

    def authorize(
        self,
        *,
        device_id: str = "",
        entry_token: str = "",
        captcha_token: str = "",
        role: str = "",
        categories: Optional[Sequence[str]] = None,
        ttl: int = 3600,
        admin_secret: str = "",
    ) -> Dict[str, Any]:
        """Mint a role-scoped device token. Remote: POST /v1/keys/authorize.
        Local: mint against the configured secret with an audit entry."""
        secret = admin_secret or os.getenv("SCOUT_BLACKBOARD_TOKEN_SECRET", "") or ""
        proof = {}
        if entry_token:
            proof["entry_token"] = entry_token
        if captcha_token:
            proof["captcha_token"] = captcha_token
        if self._local:
            if not secret:
                raise RuntimeError("SCOUT_BLACKBOARD_TOKEN_SECRET unset; cannot mint local token")
            token = auth.mint_token(
                secret, role=role or "alert",
                categories=list(categories or ["pipeline"]),
                device_id=device_id or "local", ttl=ttl,
            )
            return {"ok": True, "token": token, "claims": auth.parse_token(token), "expires_in": ttl, "mode": "local"}
        return self._http("POST", "/v1/keys/authorize", {
            "device_id": device_id,
            "proof": proof,
            "role": role,
            "categories": list(categories or ["pipeline"]),
            "ttl": ttl,
        })

    def issue(
        self,
        *,
        role: str,
        categories: Sequence[str],
        device_id: str = "",
        ttl: int = 3600,
        admin_secret: str = "",
    ) -> Dict[str, Any]:
        """Master-secret token mint for manager/CLI (moderation path)."""
        secret = admin_secret or os.getenv("SCOUT_BLACKBOARD_TOKEN_SECRET", "") or ""
        if self._local:
            if not secret:
                raise RuntimeError("SCOUT_BLACKBOARD_TOKEN_SECRET unset; cannot mint local token")
            token = auth.mint_token(
                secret, role=role, categories=list(categories),
                device_id=device_id, ttl=ttl,
            )
            return {"ok": True, "token": token, "claims": auth.parse_token(token), "expires_in": ttl, "mode": "local"}
        return self._http("POST", "/v1/keys/issue", {
            "role": role,
            "categories": list(categories),
            "device_id": device_id,
            "ttl": ttl,
        }, headers={"X-Scout-Admin": secret})

    def revoke(self, jti: str, *, admin_secret: str = "") -> Dict[str, Any]:
        secret = admin_secret or os.getenv("SCOUT_BLACKBOARD_TOKEN_SECRET", "") or ""
        if self._local:
            if not secret:
                raise RuntimeError("SCOUT_BLACKBOARD_TOKEN_SECRET unset")
            return {"ok": True, "revoked_jti": jti, "mode": "local"}
        return self._http("POST", "/v1/keys/revoke", {"jti": jti}, headers={"X-Scout-Admin": secret})

    def audit(self, *, limit: int = 200, admin_secret: str = "") -> Dict[str, Any]:
        """Manager-moderated audit log + per-token volume (flood watch)."""
        if self._local:
            secret = admin_secret or os.getenv("SCOUT_BLACKBOARD_TOKEN_SECRET", "") or ""
            if not secret:
                raise RuntimeError("SCOUT_BLACKBOARD_TOKEN_SECRET unset")
            return {"events": [], "volume": {}, "mode": "local",
                    "note": "local store has no audit trail; run the HTTP server for moderation"}
        return self._http("GET", f"/v1/audit?limit={int(limit)}")

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
