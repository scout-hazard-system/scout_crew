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

"""Minimal multi-machine HTTP frontend for the Scout blackboard.

  python -m scout_crew.blackboard.server --host 0.0.0.0 --port 8765

Key authorization (token auth): when SCOUT_BLACKBOARD_TOKEN_SECRET is set, data
endpoints require a category-scoped bearer token. Tokens are minted at runtime:

  POST /v1/keys/authorize  proof-gated (entry token) -> device-id + role-scoped token
  POST /v1/keys/issue      master-secret (X-Scout-Admin) -> manager/CLI tokens
  POST /v1/keys/revoke     master-secret -> revoke a token jti
  GET  /v1/audit           manager bearer token -> moderation/audit log + per-token volume

No bootstrap or deploy-time minting. Memory mode (--memory) runs the store in
RAM for per-peer sandbox contexts; the hub stays file-backed.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, Optional
from urllib.parse import parse_qs, urlparse

from scout_crew.blackboard import auth
from scout_crew.blackboard.store import BlackboardStore

MAX_AUDIT = 2000


class ServerState:
    """Mutable per-server state shared across handler threads."""

    def __init__(
        self,
        store: BlackboardStore,
        secret: str = "",
        entry_token: str = "",
    ) -> None:
        self.store = store
        self.secret = secret
        self.entry_token = entry_token
        self.revoked: set[str] = set()
        self.audit: Deque[Dict[str, Any]] = deque(maxlen=MAX_AUDIT)
        self.volume: Dict[str, int] = {}
        self._lock = threading.RLock()

    def log(self, kind: str, **fields: Any) -> Dict[str, Any]:
        event = {"ts": time.time(), "kind": kind, **fields}
        with self._lock:
            self.audit.append(event)
            jti = (fields.get("jti") or "").strip()
            if jti:
                self.volume[jti] = self.volume.get(jti, 0) + 1
        return event

    def audit_snapshot(self, limit: int = 200) -> Dict[str, Any]:
        with self._lock:
            events = list(self.audit)[-limit:]
            volume = dict(sorted(self.volume.items(), key=lambda kv: -kv[1])[:50])
        return {"events": events, "volume": volume}

    def revoke(self, jti: str) -> None:
        with self._lock:
            self.revoked.add(jti)


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: Any) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _bearer_token(handler: BaseHTTPRequestHandler) -> str:
    header = handler.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[len("bearer ") :].strip()
    return ""


def _client_ip(handler: BaseHTTPRequestHandler, state: ServerState) -> str:
    return handler.client_address[0]


def make_handler(state: ServerState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # quieter
            print(f"[blackboard] {self.address_string()} {fmt % args}")

        # ---- auth helpers -------------------------------------------------

        def _require_token(self) -> Optional[Dict[str, Any]]:
            """Return verified claims, or write a 401/403 and return None."""
            if not state.secret:
                return {}  # auth disabled
            token = _bearer_token(self)
            if not token:
                return self._reject(401, "missing bearer token")
            try:
                claims = auth.verify_token(state.secret, token)
            except auth.TokenError as exc:
                state.log("deny", why=str(exc), ip=_client_ip(self, state))
                return self._reject(401, f"invalid token: {exc}")
            jti = str(claims.get("jti") or "")
            if jti in state.revoked:
                state.log("deny", why="revoked", jti=jti, ip=_client_ip(self, state))
                return self._reject(401, "token revoked")
            return claims

        def _enforce_request(self, claims: Dict[str, Any], *, role: str, category: str, action: str) -> bool:
            """Token role/category binding. Returns True on approval."""
            if not state.secret:
                return True
            if not claims:
                return False
            cats = claims.get("categories") or []
            if not cats or category not in cats:
                state.log(
                    "deny", why="category_not_scoped", role=role, category=category,
                    action=action, jti=claims.get("jti"), ip=_client_ip(self, state),
                )
                self._reject(403, f"token is not scoped to category '{category}'")
                return False
            tok_role = (claims.get("role") or "").strip().lower()
            req_role = (role or "").strip().lower()
            if req_role and req_role != tok_role and not (tok_role == "manager" and action in {"read", "snapshot", "audit"}):
                self._reject(403, f"token role '{tok_role}' does not match requested role '{req_role}'")
                return False
            return True

        def _reject(self, code: int, message: str):
            _json_response(self, code, {"error": message})
            return None

        def _require_admin(self) -> bool:
            """Master-secret gate (X-Scout-Admin) for issue/revoke."""
            if not state.secret or self.headers.get("X-Scout-Admin") != state.secret:
                self._reject(401, "admin secret required (X-Scout-Admin)")
                return False
            return True

        # ---- HTTP --------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            try:
                if parsed.path in {"/", "/health"}:
                    return _json_response(self, 200, {"ok": True, "service": "scout-blackboard", "auth": bool(state.secret)})
                if parsed.path == "/v1/stats":
                    return _json_response(self, 200, state.store.stats())
                if parsed.path == "/v1/audit":
                    claims = self._require_token()
                    if claims is None:
                        return
                    if (claims.get("role") or "").lower() != "manager":
                        return self._reject(403, "audit requires a manager token")
                    state.log("audit", role="manager", jti=claims.get("jti"), ip=_client_ip(self, state))
                    return _json_response(self, 200, state.audit_snapshot(limit=int(qs.get("limit") or 200)))
                if parsed.path in {"/v1/read", "/v1/snapshot"}:
                    claims = self._require_token()
                    if claims is None:
                        return
                    role = qs.get("role") or "hermes"
                    category = qs.get("category") or "pipeline"
                    if not self._enforce_request(claims, role=role, category=category, action="read"):
                        return
                    if parsed.path == "/v1/read":
                        limit = int(qs.get("limit") or 20)
                        since = float(qs["since"]) if qs.get("since") else None
                        entries = state.store.read(
                            category=category,
                            role=role,
                            limit=limit,
                            active_only=qs.get("active_only", "1") not in {"0", "false", "False"},
                            kind=qs.get("kind"),
                            tag=qs.get("tag"),
                            query=qs.get("query"),
                            since=since,
                        )
                        state.log("read", role=role, category=category, jti=claims.get("jti"), ip=_client_ip(self, state))
                        return _json_response(self, 200, [e.to_dict() for e in entries])
                    snap = state.store.snapshot(
                        role=role,
                        limit_per_category=int(qs.get("limit_per_category") or 15),
                    )
                    state.log("snapshot", role=role, jti=claims.get("jti"), ip=_client_ip(self, state))
                    return _json_response(self, 200, snap)
                return _json_response(self, 404, {"error": "not found"})
            except PermissionError as e:
                return _json_response(self, 403, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                return _json_response(self, 400, {"error": str(e)})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload: Dict[str, Any] = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return _json_response(self, 400, {"error": "invalid json"})
            try:
                if parsed.path == "/v1/keys/authorize":
                    return self._do_authorize(payload)
                if parsed.path == "/v1/keys/issue":
                    return self._do_issue(payload)
                if parsed.path == "/v1/keys/revoke":
                    return self._do_revoke(payload)
                if parsed.path == "/v1/write":
                    if not state.secret:
                        entry = state.store.write(**payload)
                        return _json_response(self, 200, entry.to_dict())
                    claims = self._require_token()
                    if claims is None:
                        return
                    role = str(payload.get("role") or "operator")
                    category = str(payload.get("category") or "pipeline")
                    if not self._enforce_request(claims, role=role, category=category, action="write"):
                        return
                    meta = dict(payload.get("meta") or {})
                    meta.setdefault("device_id", (claims.get("device_id") or ""))
                    meta.setdefault("token_jti", (claims.get("jti") or ""))
                    write_payload = dict(payload)
                    write_payload["meta"] = meta
                    entry = state.store.write(**write_payload)
                    state.log("write", role=role, category=category, entry_kind=entry.kind, jti=claims.get("jti"), ip=_client_ip(self, state))
                    return _json_response(self, 200, entry.to_dict())
                return _json_response(self, 404, {"error": "not found"})
            except PermissionError as e:
                return _json_response(self, 403, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                return _json_response(self, 400, {"error": str(e)})

        # ---- key endpoints ----------------------------------------------

        def _do_authorize(self, payload: Dict[str, Any]) -> None:
            """Proof-gated device onboarding: assign device id + role-scoped token."""
            if not state.secret:
                return _json_response(self, 503, {"error": "key authorization not configured; set SCOUT_BLACKBOARD_TOKEN_SECRET"})
            proof = payload.get("proof") or {}
            entry_proof = str(proof.get("entry_token") or "").strip()
            captcha = str(proof.get("captcha_token") or "").strip()
            if state.entry_token:
                if not entry_proof or not self._secure_eq(entry_proof, state.entry_token):
                    state.log("deny", why="bad_entry_proof", ip=_client_ip(self, state))
                    return _json_response(self, 401, {"error": "invalid entry proof"})
            elif not entry_proof and not captcha:
                # Framework seam: production forwards a signed proof from the
                # in-app web mirror (captcha + network presence). Without the
                # entry token configured we require at least a proof marker so
                # authorize is never a password-less bearer faucet.
                return _json_response(self, 401, {"error": "entry proof required"})
            sent_device = str(payload.get("device_id") or "").strip()
            device_id = sent_device or uuid.uuid4().hex
            role = str(payload.get("role") or self._default_role()).strip().lower() or "operator"
            categories = [
                str(c).strip().lower()
                for c in (payload.get("categories") or ["pipeline"])
                if str(c).strip()
            ] or ["pipeline"]
            ttl = max(60, min(int(payload.get("ttl") or 3600), 86400))
            token = auth.mint_token(
                state.secret,
                role=role,
                categories=categories,
                device_id=device_id,
                ttl=ttl,
                extra={
                    "observed_ip": _client_ip(self, state),
                    "kind": "device",
                },
            )
            claims = auth.parse_token(token)
            state.log(
                "authorize", role=role, device_id=device_id,
                jti=claims["jti"], ip=_client_ip(self, state), categories=categories,
            )
            return _json_response(
                self, 200,
                {
                    "ok": True,
                    "token": token,
                    "device_id": device_id,
                    "role": role,
                    "categories": categories,
                    "expires_in": ttl,
                    "observed_ip": _client_ip(self, state),
                },
            )

        def _do_issue(self, payload: Dict[str, Any]) -> None:
            """Master-secret token mint for manager/CLI (moderation path)."""
            if not self._require_admin():
                return
            role = str(payload.get("role") or "operator").strip().lower()
            categories = [
                str(c).strip().lower()
                for c in (payload.get("categories") or ["pipeline"])
                if str(c).strip()
            ]
            if not categories:
                return _json_response(self, 400, {"error": "categories required"})
            device_id = str(payload.get("device_id") or "").strip()
            ttl = max(60, min(int(payload.get("ttl") or 3600), 86400))
            token = auth.mint_token(
                state.secret, role=role, categories=categories,
                device_id=device_id, ttl=ttl,
            )
            claims = auth.parse_token(token)
            state.log("issue", role=role, device_id=device_id, jti=claims["jti"], ip=_client_ip(self, state), categories=categories)
            return _json_response(
                self, 200,
                {"ok": True, "token": token, "claims": claims, "expires_in": ttl},
            )

        def _do_revoke(self, payload: Dict[str, Any]) -> None:
            if not self._require_admin():
                return
            jti = str(payload.get("jti") or "").strip()
            if not jti:
                return _json_response(self, 400, {"error": "jti required"})
            state.revoke(jti)
            state.log("revoke", jti=jti, ip=_client_ip(self, state))
            return _json_response(self, 200, {"ok": True, "revoked_jti": jti})

        @staticmethod
        def _secure_eq(a: str, b: str) -> bool:
            import hmac

            return hmac.compare_digest(a, b)

        def _default_role(self) -> str:
            writers = getattr(state.store, "sandbox_writers", None)
            if writers:
                return sorted(writers)[0]
            return "alert"

    return Handler


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scout multi-machine blackboard server")
    p.add_argument("--host", default=os.getenv("SCOUT_BLACKBOARD_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.getenv("SCOUT_BLACKBOARD_PORT", "8765")))
    p.add_argument("--db", default=os.getenv("SCOUT_BLACKBOARD_PATH", ""))
    p.add_argument(
        "--memory",
        action="store_true",
        default=os.getenv("SCOUT_BLACKBOARD_MEMORY", "0") not in {"", "0", "false", "False"},
        help="Run store in RAM (per-peer sandbox context). Hub stays file-backed.",
    )
    p.add_argument("--secret", default=os.getenv("SCOUT_BLACKBOARD_TOKEN_SECRET", ""))
    p.add_argument("--entry-token", default=os.getenv("SCOUT_BLACKBOARD_ENTRY_TOKEN", ""))
    p.add_argument(
        "--sandbox-writers",
        default=os.getenv("SCOUT_BLACKBOARD_SANDBOX_WRITERS", ""),
        help="CSV roles allowed to write raw pipeline entries (default: alert via ACL)",
    )
    args = p.parse_args(argv)
    db = Path(args.db).expanduser() if args.db else None
    sandbox_writers = None
    if args.sandbox_writers.strip():
        sandbox_writers = [w.strip() for w in args.sandbox_writers.split(",") if w.strip()]
    store = BlackboardStore(db_path=db, memory=args.memory, sandbox_writers=sandbox_writers)
    state = ServerState(store, secret=args.secret, entry_token=args.entry_token)
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    except OSError as exc:
        print(f"scout blackboard: cannot bind {args.host}:{args.port} — {exc}")
        return 1
    print(f"scout blackboard listening on http://{args.host}:{args.port}")
    print(f"db={store.db_path} mode={'memory' if store.memory else 'file'}")
    print(f"auth={'enabled' if state.secret else 'disabled'} sandbox_writers={sorted(store.sandbox_writers) if store.sandbox_writers is not None else 'acl-only'}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutdown")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())