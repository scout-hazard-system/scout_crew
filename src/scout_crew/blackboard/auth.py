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

"""Token machinery for the Scout blackboard (key authorization).

No bootstrap minting: tokens are minted at runtime through
POST /v1/keys/authorize (proof-gated, device-id assignment, no IMEI) or
POST /v1/keys/issue (master-secret grab, manager/CLI). The server signs tokens
with SCOUT_BLACKBOARD_TOKEN_SECRET using pure-stdlib HMAC-SHA256.

Token format:  base64url(payload) "." base64url(hmac_sha256(secret, payload))
Claims: scope, role, categories, device_id, iat, exp, jti (+ optional extras).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Iterable, Optional

TOKEN_SCOPE = "scout_blackboard_v1"


class TokenError(ValueError):
    """Raised when a token is malformed, forged, or expired."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + pad)
    except Exception as exc:  # noqa: BLE001
        raise TokenError("malformed token payload") from exc


def _sign(secret: str, payload_b64: str) -> str:
    return _b64e(hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest())


def random_secret() -> str:
    """Fresh 32-byte secret for SCOUT_BLACKBOARD_TOKEN_SECRET."""
    return secrets.token_hex(32)


def mint_token(
    secret: str,
    *,
    role: str,
    categories: Iterable[str],
    device_id: str = "",
    ttl: int = 3600,
    now: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """Mint a role-scoped bearer token signed with the server secret."""
    now_f = float(now) if now is not None else time.time()
    claims: Dict[str, Any] = {
        "scope": TOKEN_SCOPE,
        "role": (role or "").strip().lower(),
        "categories": sorted({str(c) for c in categories if str(c).strip()}),
        "device_id": (device_id or "").strip(),
        "iat": int(now_f),
        "exp": int(now_f) + max(1, int(ttl)),
        "jti": secrets.token_hex(8),
    }
    if extra:
        claims.update(extra)
    payload_b64 = _b64e(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign(secret, payload_b64)}"


def parse_token(token: str) -> Dict[str, Any]:
    """Decode claims without verifying (for audit display)."""
    try:
        payload_b64, _sig = token.split(".", 1)
    except ValueError as exc:
        raise TokenError("malformed token") from exc
    return json.loads(_b64d(payload_b64))


def verify_token(
    secret: str,
    token: str,
    *,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Verify signature + freshness. Returns claims or raises TokenError."""
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError as exc:
        raise TokenError("malformed token") from exc
    expected = _sign(secret, payload_b64)
    if not hmac.compare_digest(expected, sig):
        raise TokenError("bad signature")
    claims = json.loads(_b64d(payload_b64))
    if claims.get("scope") != TOKEN_SCOPE:
        raise TokenError("wrong scope")
    now_f = float(now) if now is not None else time.time()
    exp = int(claims.get("exp") or 0)
    if exp and now_f > exp:
        raise TokenError("token expired")
    return claims


def default_secret() -> str:
    """Return the configured server secret or an empty string (auth disabled)."""
    return (os.getenv("SCOUT_BLACKBOARD_TOKEN_SECRET") or "").strip()


def authorized_categories(claims: Dict[str, Any], category: str) -> bool:
    """True if the token covers this category (empty categories = uncategorized token)."""
    cats = claims.get("categories") or []
    return bool(cats) and category in cats