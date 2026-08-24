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

Clients set:
  SCOUT_BLACKBOARD_URL=http://<this-host>:8765
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from scout_crew.blackboard.store import BlackboardStore


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: Any) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def make_handler(store: BlackboardStore):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # quieter
            print(f"[blackboard] {self.address_string()} {fmt % args}")

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            try:
                if parsed.path in {"/", "/health"}:
                    return _json_response(self, 200, {"ok": True, "service": "scout-blackboard"})
                if parsed.path == "/v1/stats":
                    return _json_response(self, 200, store.stats())
                if parsed.path == "/v1/read":
                    limit = int(qs.get("limit") or 20)
                    since = float(qs["since"]) if qs.get("since") else None
                    entries = store.read(
                        category=qs.get("category") or "pipeline",
                        role=qs.get("role") or "hermes",
                        limit=limit,
                        active_only=qs.get("active_only", "1") not in {"0", "false", "False"},
                        kind=qs.get("kind"),
                        tag=qs.get("tag"),
                        query=qs.get("query"),
                        since=since,
                    )
                    return _json_response(self, 200, [e.to_dict() for e in entries])
                if parsed.path == "/v1/snapshot":
                    snap = store.snapshot(
                        role=qs.get("role") or "hermes",
                        limit_per_category=int(qs.get("limit_per_category") or 15),
                    )
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
                if parsed.path == "/v1/write":
                    entry = store.write(**payload)
                    return _json_response(self, 200, entry.to_dict())
                return _json_response(self, 404, {"error": "not found"})
            except PermissionError as e:
                return _json_response(self, 403, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                return _json_response(self, 400, {"error": str(e)})

    return Handler


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scout multi-machine blackboard server")
    p.add_argument("--host", default=os.getenv("SCOUT_BLACKBOARD_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.getenv("SCOUT_BLACKBOARD_PORT", "8765")))
    p.add_argument("--db", default=os.getenv("SCOUT_BLACKBOARD_PATH", ""))
    args = p.parse_args(argv)
    db = Path(args.db).expanduser() if args.db else None
    store = BlackboardStore(db_path=db)
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    print(f"scout blackboard listening on http://{args.host}:{args.port}")
    print(f"db={store.db_path}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
