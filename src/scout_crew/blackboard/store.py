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

"""SQLite-backed categorized blackboard with role ACLs.

Categories
----------
pipeline   — general multi-agent pipeline facts (specialist writers)
dev_debug  — dev-only debug / rewrite notes

Roles
-----
alert, intel, vet, rank, core — write pipeline; read all
manager                      — read all; write pipeline summaries/rewrites only
dev                          — write/read dev_debug; read pipeline
hermes                       — read-only all categories
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

CATEGORIES = ("pipeline", "dev_debug")

# action -> allowed roles for write
ROLE_ACL: Dict[str, Dict[str, Sequence[str]]] = {
    "pipeline": {
        "read": (
            "alert",
            "intel",
            "vet",
            "rank",
            "core",
            "manager",
            "dev",
            "hermes",
            "operator",
        ),
        "write": ("alert", "intel", "vet", "rank", "core"),
        # manager may only post summary/rewrite kind entries on pipeline
        "summarize": ("manager",),
    },
    "dev_debug": {
        "read": ("dev", "manager", "hermes", "operator"),
        "write": ("dev",),
        "summarize": ("dev",),  # dev may rewrite own debug notes
    },
}

KIND_RAW = "raw"
KIND_SUMMARY = "summary"
KIND_REWRITE = "rewrite"


def _default_db_path() -> Path:
    env = os.getenv("SCOUT_BLACKBOARD_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    # project data dir
    root = Path(__file__).resolve().parents[3]
    return (root / "data" / "blackboard" / "scout_blackboard.db").resolve()


@dataclass
class Entry:
    id: str
    category: str
    kind: str
    role: str
    author: str
    host: str
    title: str
    body: str
    tags: List[str]
    meta: Dict[str, Any]
    created_at: float
    updated_at: float
    superseded_by: Optional[str] = None
    active: int = 1

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


class BlackboardStore:
    """Thread-safe SQLite store (WAL) suitable for local multi-process + HTTP frontends."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    role TEXT NOT NULL,
                    author TEXT NOT NULL,
                    host TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    meta TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    superseded_by TEXT,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_cat_active_time "
                "ON entries(category, active, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_role ON entries(role, category)"
            )

    @staticmethod
    def normalize_role(role: str) -> str:
        r = (role or "").strip().lower()
        aliases = {
            "local_manager": "manager",
            "mgr": "manager",
            "admin": "manager",
            "dev_specialist": "dev",
            "scout-dev": "dev",
            "alert_specialist": "alert",
            "intel_specialist": "intel",
            "vet_specialist": "vet",
            "rank_specialist": "rank",
            "core_specialist": "core",
            "scout-hermes": "hermes",
            "hermes-hc": "hermes",
            "scout-hermes-hc": "hermes",
            "scout-hermes-hc1.0.0": "hermes",
        }
        return aliases.get(r, r)

    @staticmethod
    def normalize_category(category: str) -> str:
        c = (category or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "general": "pipeline",
            "pipe": "pipeline",
            "ops": "pipeline",
            "debug": "dev_debug",
            "dev": "dev_debug",
            "rewrite": "dev_debug",
            "dev_rewrite": "dev_debug",
            "debug_rewrite": "dev_debug",
        }
        c = aliases.get(c, c)
        if c not in CATEGORIES:
            raise ValueError(f"unknown category '{category}'; expected one of {CATEGORIES}")
        return c

    def check_perm(self, role: str, category: str, action: str) -> None:
        role_n = self.normalize_role(role)
        cat = self.normalize_category(category)
        allowed = ROLE_ACL[cat].get(action) or ()
        if role_n not in allowed:
            raise PermissionError(
                f"role '{role_n}' cannot {action} on category '{cat}'. "
                f"allowed={list(allowed)}"
            )

    def write(
        self,
        *,
        category: str,
        role: str,
        title: str,
        body: str,
        kind: str = KIND_RAW,
        tags: Optional[Iterable[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
        author: Optional[str] = None,
        supersede_id: Optional[str] = None,
    ) -> Entry:
        role_n = self.normalize_role(role)
        cat = self.normalize_category(category)
        kind_n = (kind or KIND_RAW).strip().lower()
        if kind_n not in {KIND_RAW, KIND_SUMMARY, KIND_REWRITE}:
            raise ValueError(f"invalid kind '{kind}'")

        # ACL
        if cat == "pipeline" and kind_n in {KIND_SUMMARY, KIND_REWRITE}:
            self.check_perm(role_n, cat, "summarize")
        else:
            self.check_perm(role_n, cat, "write")

        now = time.time()
        entry_id = uuid.uuid4().hex
        host = socket.gethostname()
        tag_list = [str(t).strip() for t in (tags or []) if str(t).strip()]
        meta_d = dict(meta or {})
        author_n = (author or role_n).strip()

        with self._lock, self._conn() as conn:
            if supersede_id:
                conn.execute(
                    "UPDATE entries SET active=0, superseded_by=?, updated_at=? WHERE id=? AND category=?",
                    (entry_id, now, supersede_id, cat),
                )
            conn.execute(
                """
                INSERT INTO entries(
                    id, category, kind, role, author, host, title, body, tags, meta,
                    created_at, updated_at, superseded_by, active
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,1)
                """,
                (
                    entry_id,
                    cat,
                    kind_n,
                    role_n,
                    author_n,
                    host,
                    (title or "").strip()[:200] or "(untitled)",
                    (body or "").strip(),
                    json.dumps(tag_list),
                    json.dumps(meta_d),
                    now,
                    now,
                ),
            )
        return self.get(entry_id)  # type: ignore[return-value]

    def get(self, entry_id: str) -> Optional[Entry]:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        return self._row_to_entry(row) if row else None

    def read(
        self,
        *,
        category: str,
        role: str,
        limit: int = 20,
        active_only: bool = True,
        kind: Optional[str] = None,
        tag: Optional[str] = None,
        query: Optional[str] = None,
        since: Optional[float] = None,
    ) -> List[Entry]:
        role_n = self.normalize_role(role)
        cat = self.normalize_category(category)
        self.check_perm(role_n, cat, "read")
        limit = max(1, min(int(limit or 20), 200))

        clauses = ["category=?"]
        params: List[Any] = [cat]
        if active_only:
            clauses.append("active=1")
        if kind:
            clauses.append("kind=?")
            params.append(kind.strip().lower())
        if since is not None:
            clauses.append("created_at>=?")
            params.append(float(since))
        if query:
            clauses.append("(title LIKE ? OR body LIKE ? OR tags LIKE ?)")
            q = f"%{query.strip()}%"
            params.extend([q, q, q])
        if tag:
            clauses.append("tags LIKE ?")
            params.append(f"%{tag.strip()}%")

        sql = (
            f"SELECT * FROM entries WHERE {' AND '.join(clauses)} "
            f"ORDER BY created_at DESC LIMIT ?"
        )
        params.append(limit)
        with self._lock, self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def snapshot(
        self,
        *,
        role: str,
        categories: Optional[Sequence[str]] = None,
        limit_per_category: int = 15,
    ) -> Dict[str, List[Dict[str, Any]]]:
        cats = list(categories) if categories else list(CATEGORIES)
        out: Dict[str, List[Dict[str, Any]]] = {}
        for cat in cats:
            try:
                entries = self.read(
                    category=cat, role=role, limit=limit_per_category, active_only=True
                )
            except PermissionError:
                continue
            out[cat] = [e.to_dict() for e in entries]
        return out

    def stats(self) -> Dict[str, Any]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT category, kind, COUNT(*) AS n, SUM(active) AS active_n "
                "FROM entries GROUP BY category, kind"
            ).fetchall()
        return {
            "db_path": str(self.db_path),
            "host": socket.gethostname(),
            "counts": [dict(r) for r in rows],
        }

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> Entry:
        return Entry(
            id=row["id"],
            category=row["category"],
            kind=row["kind"],
            role=row["role"],
            author=row["author"],
            host=row["host"],
            title=row["title"],
            body=row["body"],
            tags=json.loads(row["tags"] or "[]"),
            meta=json.loads(row["meta"] or "{}"),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            superseded_by=row["superseded_by"],
            active=int(row["active"]),
        )
