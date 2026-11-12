from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Literal

MemoryKind = Literal["style", "outcome"]

DB_PATH = Path(os.getenv("GIGBID_DB_PATH", "data/processed/gigbid.sqlite3"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS promoted_memory ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, kind TEXT NOT NULL, "
        "content TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    return conn


def add_memory(
    tenant_id: str,
    kind: MemoryKind,
    content: str,
    source: str,
    *,
    explicitly_approved: bool,
) -> int:
    if not explicitly_approved:
        raise PermissionError("Memory promotion requires explicit user approval")
    if not tenant_id.strip() or not content.strip() or len(content) > 1000:
        raise ValueError(
            "tenant, non-empty content, and a maximum 1000-character memory are required"
        )
    if kind not in {"style", "outcome"}:
        raise ValueError("kind must be 'style' or 'outcome'")
    if kind == "style" and source != "repeated_user_edit":
        raise ValueError("Style memory can only be promoted from repeated user edits")
    if kind == "outcome" and source != "verified_marketplace_outcome":
        raise ValueError("Outcome memory requires a verified marketplace result")
    conn = _connect()
    try:
        cursor = conn.execute(
            "INSERT INTO promoted_memory (tenant_id, kind, content, source) VALUES (?, ?, ?, ?)",
            (tenant_id, kind, content.strip(), source),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def list_memory(tenant_id: str, kind: MemoryKind | None = None) -> list[dict[str, str | int]]:
    conn = _connect()
    try:
        if kind is None:
            rows = conn.execute(
                "SELECT id, kind, content, source, created_at FROM promoted_memory "
                "WHERE tenant_id=? ORDER BY id DESC",
                (tenant_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, kind, content, source, created_at FROM promoted_memory "
                "WHERE tenant_id=? AND kind=? ORDER BY id DESC",
                (tenant_id, kind),
            ).fetchall()
        return [
            {
                "id": row[0],
                "kind": row[1],
                "content": row[2],
                "source": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]
    finally:
        conn.close()


def delete_memory(tenant_id: str, memory_id: int) -> bool:
    if memory_id < 1:
        raise ValueError("memory_id must be positive")
    conn = _connect()
    try:
        cursor = conn.execute(
            "DELETE FROM promoted_memory WHERE id=? AND tenant_id=?", (memory_id, tenant_id)
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()
