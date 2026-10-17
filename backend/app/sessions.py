"""Conversational session store.

Lives in data/sessions.db, separate from the rebuilt school catalog, so
ingesting public data does not wipe chats.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .schemas import ChatMessage, Household, Preferences, RecommendResponse

ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = ROOT / "data" / "sessions.db"
MESSAGE_CAP = 40

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    preferences_json TEXT NOT NULL DEFAULT '{}',
    origin_lat REAL,
    origin_lon REAL,
    origin_label TEXT,
    last_response_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS households (
    id TEXT PRIMARY KEY,
    household_json TEXT NOT NULL DEFAULT '{}',
    work_lat REAL,
    work_lon REAL,
    work_label TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _migrate(con: sqlite3.Connection) -> None:
    cols = {row["name"] for row in con.execute("PRAGMA table_info(sessions)")}
    if "household_id" not in cols:
        con.execute("ALTER TABLE sessions ADD COLUMN household_id TEXT")
    if "asked_json" not in cols:
        con.execute("ALTER TABLE sessions ADD COLUMN asked_json TEXT NOT NULL DEFAULT '[]'")


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path else SESSIONS_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.isolation_level = None
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(_SCHEMA)
    _migrate(con)
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_session(con: sqlite3.Connection, household_id: Optional[str] = None) -> str:
    sid = uuid.uuid4().hex
    now = _now()
    with _lock:
        if household_id is not None:
            exists = con.execute("SELECT 1 FROM households WHERE id = ?", (household_id,)).fetchone()
            if exists is None:
                household_id = None
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute(
                "INSERT INTO sessions (id, preferences_json, household_id, created_at, updated_at) VALUES (?, '{}', ?, ?, ?)",
                (sid, household_id, now, now),
            )
            con.commit()
        except Exception:
            con.rollback()
            raise
    return sid


# ----------------------------------------------------------------------------------
# Households: facts that outlive one chat
# ----------------------------------------------------------------------------------


def _household_from_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        household = Household.model_validate(json.loads(row["household_json"] or "{}"))
    except Exception:
        household = Household()
    work = None
    if row["work_lat"] is not None and row["work_lon"] is not None:
        work = (float(row["work_lat"]), float(row["work_lon"]))
    return {
        "id": row["id"],
        "household": household,
        "work": work,
        "work_label": row["work_label"],
        "updated_at": row["updated_at"],
    }


def get_household(con: sqlite3.Connection, household_id: Optional[str]) -> Optional[dict[str, Any]]:
    if not household_id:
        return None
    with _lock:
        row = con.execute("SELECT * FROM households WHERE id = ?", (household_id,)).fetchone()
    return _household_from_row(row) if row is not None else None


def ensure_household(con: sqlite3.Connection, session_id: str, household_id: Optional[str]) -> str:
    """Return the household attached to the session, attaching or creating one when needed."""
    with _lock:
        row = con.execute("SELECT household_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        current = row["household_id"] if row is not None else None
        if current and con.execute("SELECT 1 FROM households WHERE id = ?", (current,)).fetchone():
            return current
        now = _now()
        con.execute("BEGIN IMMEDIATE")
        try:
            if household_id and con.execute("SELECT 1 FROM households WHERE id = ?", (household_id,)).fetchone():
                hid = household_id
            else:
                hid = uuid.uuid4().hex
                con.execute(
                    "INSERT INTO households (id, household_json, created_at, updated_at) VALUES (?, '{}', ?, ?)",
                    (hid, now, now),
                )
            con.execute("UPDATE sessions SET household_id = ?, updated_at = ? WHERE id = ?", (hid, now, session_id))
            con.commit()
        except Exception:
            con.rollback()
            raise
    return hid


def save_household(
    con: sqlite3.Connection,
    household_id: str,
    household: Household,
    work: Optional[tuple[float, float]],
    work_label: Optional[str],
) -> None:
    with _lock:
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute(
                """UPDATE households
                   SET household_json = ?, work_lat = ?, work_lon = ?, work_label = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    json.dumps(household.model_dump(mode="json")),
                    work[0] if work else None,
                    work[1] if work else None,
                    work_label,
                    _now(),
                    household_id,
                ),
            )
            con.commit()
        except Exception:
            con.rollback()
            raise


def delete_household(con: sqlite3.Connection, household_id: str) -> bool:
    with _lock:
        row = con.execute("SELECT 1 FROM households WHERE id = ?", (household_id,)).fetchone()
        if row is None:
            return False
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute("UPDATE sessions SET household_id = NULL WHERE household_id = ?", (household_id,))
            con.execute("DELETE FROM households WHERE id = ?", (household_id,))
            con.commit()
        except Exception:
            con.rollback()
            raise
    return True


def get_session(con: sqlite3.Connection, session_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        row = con.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        message_rows = con.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    prefs_raw = json.loads(row["preferences_json"] or "{}")
    try:
        prefs = Preferences.model_validate(prefs_raw)
    except Exception:
        prefs = Preferences()
    origin = None
    if row["origin_lat"] is not None and row["origin_lon"] is not None:
        origin = (float(row["origin_lat"]), float(row["origin_lon"]))
    recommendation = None
    if row["last_response_json"]:
        try:
            recommendation = RecommendResponse.model_validate(json.loads(row["last_response_json"]))
        except Exception:
            recommendation = None
    household_id = row["household_id"] if "household_id" in row.keys() else None
    asked: list[str] = []
    if "asked_json" in row.keys() and row["asked_json"]:
        try:
            asked = [str(t) for t in json.loads(row["asked_json"])]
        except Exception:
            asked = []
    return {
        "id": row["id"],
        "preferences": prefs,
        "origin": origin,
        "origin_label": row["origin_label"],
        "messages": [ChatMessage(role=m["role"], content=m["content"]) for m in message_rows],
        "recommendation": recommendation,
        "household_id": household_id,
        "asked": asked,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def save_turn(
    con: sqlite3.Connection,
    session_id: str,
    prefs: Preferences,
    origin: Optional[tuple[float, float]],
    origin_label: Optional[str],
    user_message: str,
    assistant_message: str,
    response: dict[str, Any],
    asked: Optional[list[str]] = None,
) -> None:
    now = _now()
    lat = origin[0] if origin else None
    lon = origin[1] if origin else None
    with _lock:
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute(
                """UPDATE sessions
                   SET preferences_json = ?, origin_lat = ?, origin_lon = ?, origin_label = ?,
                       last_response_json = ?, asked_json = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    json.dumps(prefs.model_dump(mode="json")),
                    lat,
                    lon,
                    origin_label,
                    json.dumps(response),
                    json.dumps(list(asked or [])),
                    now,
                    session_id,
                ),
            )
            con.executemany(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                [
                    (session_id, "user", user_message, now),
                    (session_id, "assistant", assistant_message, now),
                ],
            )
            con.execute(
                """DELETE FROM messages WHERE session_id = ? AND id NOT IN (
                       SELECT id FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?
                   )""",
                (session_id, session_id, MESSAGE_CAP),
            )
            con.commit()
        except Exception:
            con.rollback()
            raise


def clear_origin(con: sqlite3.Connection, session_id: str) -> bool:
    """Drop stored coordinates. Place names in preferences are left alone."""
    with _lock:
        row = con.execute("SELECT last_response_json FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return False
        payload = row["last_response_json"]
        if payload:
            try:
                data = json.loads(payload)
                data["origin"] = None
                payload = json.dumps(data)
            except Exception:
                payload = row["last_response_json"]
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute(
                """UPDATE sessions
                   SET origin_lat = NULL, origin_lon = NULL, origin_label = NULL,
                       last_response_json = ?, updated_at = ?
                   WHERE id = ?""",
                (payload, _now(), session_id),
            )
            con.commit()
        except Exception:
            con.rollback()
            raise
    return True


def delete_session(con: sqlite3.Connection, session_id: str) -> None:
    with _lock:
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            con.commit()
        except Exception:
            con.rollback()
            raise
