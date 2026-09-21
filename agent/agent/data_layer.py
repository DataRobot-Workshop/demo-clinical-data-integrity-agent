# Copyright 2026 DataRobot, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Data access for the Clinical Data Integrity Agent.

Snowflake is the system of record for the workshop. Every read of the flagged
encounters and every write-back of an approved correction goes through here, so
the tools in tools.py stay free of connection details.

Two backends are supported:

* Snowflake (default) — direct SQL via snowflake-connector-python authenticated
  with a Programmatic Access Token (PAT). This mirrors what Snowflake-Labs/mcp
  does under the hood; the PAT is resolved from Config (SNOWFLAKE_PAT), never
  hard-coded.
* Local SQLite scratch (demo.db) — enabled with USE_LOCAL_SQLITE=true, or used
  automatically when no PAT is configured. This is only a scratch copy for local
  iteration without burning trial credits; it is not the system of record.

The two objects the agent touches:

* flagged_encounters   — a view of encounters whose diagnosis code was flagged
                         as not matching the clinical documentation.
* encounters / audit_log — the base table updated on approval, plus the append
                         only audit trail that records who approved what, when,
                         and why. That audit trail is the point of the demo.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .config import Config

# Columns the flagged_encounters view exposes, in a stable order.
_FLAGGED_COLUMNS = [
    "patient_id",
    "encounter_id",
    "encounter_date",
    "diagnosis_code",
    "diagnosis_description",
    "clinical_note_excerpt",
    "flag_reason",
    "status",
]


class DataLayerError(RuntimeError):
    """Raised when the data layer cannot read or write the system of record."""


def _project_root() -> Path:
    """Return the project root (where demo.db and the data files are staged).

    tools/data live at the project root, two levels up from this file
    (agent/agent/data_layer.py -> agent/agent -> agent -> <root>).
    """
    return Path(__file__).resolve().parents[2]


def _resolve_sqlite_path(config: Config) -> Path:
    raw = Path(config.local_sqlite_path)
    if raw.is_absolute():
        return raw
    return _project_root() / raw


def _use_sqlite(config: Config) -> bool:
    """Decide whether to use the SQLite scratch copy.

    Explicit opt-in via USE_LOCAL_SQLITE wins. Otherwise fall back to SQLite only
    when no PAT is available, so local dev works before Snowflake is wired up.
    """
    if config.use_local_sqlite:
        return True
    return not bool(config.snowflake_pat)


# ---------------------------------------------------------------------------
# Snowflake backend
# ---------------------------------------------------------------------------
def _snowflake_connection(config: Config) -> Any:
    if not config.snowflake_pat:
        raise DataLayerError(
            "No Snowflake PAT configured. In DataRobot it is provided via Shared "
            "Secure Configuration; locally set SNOWFLAKE_PAT to a 1Password op:// "
            "reference and run through `op run --env-file=.env -- <command>`. Or "
            "set USE_LOCAL_SQLITE=true to use the demo.db scratch copy."
        )
    try:
        import snowflake.connector
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DataLayerError(
            "snowflake-connector-python is not installed. Run "
            "`dr task run agent:install`."
        ) from exc

    # PAT auth: the secret goes in `token=` with authenticator PROGRAMMATIC_ACCESS_TOKEN
    # (the documented PAT field; `password=` is the plain-password path). Snowflake
    # still requires the user the PAT belongs to; without it the connector errors
    # with "User is empty" (251005). This avoids the key-pair / JWT setup that
    # failed previously.
    if not config.snowflake_user:
        raise DataLayerError(
            "SNOWFLAKE_USER is not set. A Programmatic Access Token authenticates "
            "as a specific user, so set SNOWFLAKE_USER to the username the PAT "
            "belongs to (in .env locally, or as a runtime parameter in DataRobot)."
        )
    connect_kwargs: dict[str, Any] = {
        "account": config.snowflake_account,
        "user": config.snowflake_user,
        "token": config.snowflake_pat,
        "authenticator": "PROGRAMMATIC_ACCESS_TOKEN",
        "warehouse": config.snowflake_warehouse,
        "database": config.snowflake_database,
        "schema": config.snowflake_schema,
    }
    if config.snowflake_role:
        connect_kwargs["role"] = config.snowflake_role
    try:
        return snowflake.connector.connect(**connect_kwargs)
    except Exception as exc:  # noqa: BLE001 - surface any connector failure clearly
        raise DataLayerError(f"Snowflake connection failed: {exc}") from exc


def _snowflake_get_flagged(config: Config) -> list[dict[str, Any]]:
    conn = _snowflake_connection(config)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM flagged_encounters")
        col_names = [c[0].lower() for c in cur.description]
        rows = cur.fetchall()
    finally:
        conn.close()
    return [_normalize_row(dict(zip(col_names, row))) for row in rows]


def _snowflake_write_back(
    config: Config,
    encounter_id: str,
    approved_code: str,
    approver: str,
    rationale: str,
    approved_at: str,
    audit_id: str,
) -> None:
    conn = _snowflake_connection(config)
    try:
        cur = conn.cursor()
        # 1. Update the base record — mark corrected and stamp who/what/when.
        cur.execute(
            """
            UPDATE encounters
               SET status = 'corrected',
                   approved_code = %(approved_code)s,
                   approved_by = %(approver)s,
                   approved_at = %(approved_at)s
             WHERE encounter_id = %(encounter_id)s
            """,
            {
                "approved_code": approved_code,
                "approver": approver,
                "approved_at": approved_at,
                "encounter_id": encounter_id,
            },
        )
        # 2. Append the audit trail row — this is the governance record.
        cur.execute(
            """
            INSERT INTO audit_log
                (audit_id, encounter_id, approved_code, approved_by,
                 approved_at, rationale)
            VALUES
                (%(audit_id)s, %(encounter_id)s, %(approved_code)s,
                 %(approver)s, %(approved_at)s, %(rationale)s)
            """,
            {
                "audit_id": audit_id,
                "encounter_id": encounter_id,
                "approved_code": approved_code,
                "approver": approver,
                "approved_at": approved_at,
                "rationale": rationale,
            },
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        raise DataLayerError(f"Snowflake write-back failed: {exc}") from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# SQLite scratch backend
# ---------------------------------------------------------------------------
def _sqlite_connection(config: Config) -> sqlite3.Connection:
    path = _resolve_sqlite_path(config)
    if not path.exists():
        raise DataLayerError(
            f"Local scratch database not found at {path}. Stage demo.db into the "
            "project root, or configure Snowflake (SNOWFLAKE_PAT)."
        )
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_get_flagged(config: Config) -> list[dict[str, Any]]:
    conn = _sqlite_connection(config)
    try:
        cur = conn.cursor()
        # The flagged_encounters view may not exist in the scratch copy; fall back
        # to filtering the encounters table on status.
        try:
            cur.execute("SELECT * FROM flagged_encounters")
        except sqlite3.OperationalError:
            cur.execute("SELECT * FROM encounters WHERE status = 'flagged'")
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    return [_normalize_row(r) for r in rows]


def _sqlite_write_back(
    config: Config,
    encounter_id: str,
    approved_code: str,
    approver: str,
    rationale: str,
    approved_at: str,
    audit_id: str,
) -> None:
    conn = _sqlite_connection(config)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE encounters
               SET status = 'corrected',
                   approved_code = ?,
                   approved_by = ?,
                   approved_at = ?
             WHERE encounter_id = ?
            """,
            (approved_code, approver, approved_at, encounter_id),
        )
        cur.execute(
            """
            INSERT INTO audit_log
                (audit_id, encounter_id, approved_code, approved_by,
                 approved_at, rationale)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (audit_id, encounter_id, approved_code, approver, approved_at, rationale),
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        raise DataLayerError(f"SQLite write-back failed: {exc}") from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Normalization + public API
# ---------------------------------------------------------------------------
def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw row into the stable flagged-encounter dict the agent expects."""
    lowered = {str(k).lower(): v for k, v in row.items()}
    out: dict[str, Any] = {}
    for col in _FLAGGED_COLUMNS:
        value = lowered.get(col)
        if isinstance(value, (_dt.date, _dt.datetime)):
            value = value.isoformat()
        out[col] = value
    return out


def get_flagged_encounters(config: Config | None = None) -> list[dict[str, Any]]:
    """Return every flagged encounter from the system of record.

    Reads `SELECT * FROM flagged_encounters` from Snowflake (default) or from the
    demo.db scratch copy when USE_LOCAL_SQLITE is set or no PAT is configured.
    """
    config = config or Config()
    if _use_sqlite(config):
        return _sqlite_get_flagged(config)
    return _snowflake_get_flagged(config)


def write_back_correction(
    encounter_id: str,
    approved_code: str,
    approver: str,
    rationale: str,
    config: Config | None = None,
) -> dict[str, Any]:
    """Persist an approved correction and append the audit trail entry.

    Updates the encounters record (status/approved_code/approved_by/approved_at)
    and inserts an immutable audit_log row. Returns the audit entry so the UI can
    show exactly what was written and who approved it.
    """
    config = config or Config()
    approved_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    audit_id = str(uuid.uuid4())

    if _use_sqlite(config):
        backend = "sqlite"
        _sqlite_write_back(
            config,
            encounter_id,
            approved_code,
            approver,
            rationale,
            approved_at,
            audit_id,
        )
    else:
        backend = "snowflake"
        _snowflake_write_back(
            config,
            encounter_id,
            approved_code,
            approver,
            rationale,
            approved_at,
            audit_id,
        )

    return {
        "status": "written",
        "backend": backend,
        "audit_log_entry": {
            "audit_id": audit_id,
            "encounter_id": encounter_id,
            "approved_code": approved_code,
            "approved_by": approver,
            "approved_at": approved_at,
            "rationale": rationale,
        },
    }


def get_audit_log(config: Config | None = None) -> list[dict[str, Any]]:
    """Return the audit trail entries, newest first, for the Audit Trail UI page."""
    config = config or Config()
    if _use_sqlite(config):
        conn = _sqlite_connection(config)
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM audit_log ORDER BY approved_at DESC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    conn = _snowflake_connection(config)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM audit_log ORDER BY approved_at DESC")
        col_names = [c[0].lower() for c in cur.description]
        rows = cur.fetchall()
        return [dict(zip(col_names, r)) for r in rows]
    finally:
        conn.close()
