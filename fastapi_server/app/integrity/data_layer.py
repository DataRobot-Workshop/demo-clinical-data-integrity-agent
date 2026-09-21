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
Snowflake / SQLite access for the Clinical Data Integrity review UI backend.

Reads flagged encounters and the audit trail, and persists approvals (UPDATE
encounters + INSERT audit_log). Snowflake is the system of record; the SQLite
demo.db path is a local scratch fallback for iterating without trial credits.
The PAT is read from Config (never hard-coded).
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from pathlib import Path
from typing import Any

from app.config import Config

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
    """Raised when the review backend cannot read or write the system of record."""


def _project_root() -> Path:
    # fastapi_server/app/integrity/data_layer.py
    #   -> integrity -> app -> fastapi_server -> <root>
    return Path(__file__).resolve().parents[3]


def _resolve_sqlite_path(config: Config) -> Path:
    raw = Path(config.local_sqlite_path)
    return raw if raw.is_absolute() else _project_root() / raw


def _use_sqlite(config: Config) -> bool:
    if config.use_local_sqlite:
        return True
    return not bool(config.snowflake_pat)


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    lowered = {str(k).lower(): v for k, v in row.items()}
    out: dict[str, Any] = {}
    for col in _FLAGGED_COLUMNS:
        value = lowered.get(col)
        if isinstance(value, (_dt.date, _dt.datetime)):
            value = value.isoformat()
        out[col] = value
    return out


# ---------------------------------------------------------------------------
# Snowflake
# ---------------------------------------------------------------------------
def _snowflake_connection(config: Config) -> Any:
    if not config.snowflake_pat:
        raise DataLayerError(
            "No Snowflake PAT configured. Set SNOWFLAKE_PAT, or USE_LOCAL_SQLITE=true."
        )
    import snowflake.connector

    # PAT auth: secret in `token=` with authenticator PROGRAMMATIC_ACCESS_TOKEN
    # (the documented PAT field; `password=` is the plain-password path). Snowflake
    # requires the user the PAT belongs to, else it errors "User is empty" (251005).
    if not config.snowflake_user:
        raise DataLayerError(
            "SNOWFLAKE_USER is not set. A Programmatic Access Token authenticates "
            "as a specific user, so set SNOWFLAKE_USER to the username the PAT "
            "belongs to."
        )
    kwargs: dict[str, Any] = {
        "account": config.snowflake_account,
        "user": config.snowflake_user,
        "token": config.snowflake_pat,
        "authenticator": "PROGRAMMATIC_ACCESS_TOKEN",
        "warehouse": config.snowflake_warehouse,
        "database": config.snowflake_database,
        "schema": config.snowflake_schema,
    }
    if config.snowflake_role:
        kwargs["role"] = config.snowflake_role
    try:
        return snowflake.connector.connect(**kwargs)
    except Exception as exc:  # noqa: BLE001
        raise DataLayerError(f"Snowflake connection failed: {exc}") from exc


def _sf_query(config: Config, sql: str) -> list[dict[str, Any]]:
    conn = _snowflake_connection(config)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [c[0].lower() for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# SQLite scratch
# ---------------------------------------------------------------------------
def _sqlite_connection(config: Config) -> sqlite3.Connection:
    path = _resolve_sqlite_path(config)
    if not path.exists():
        raise DataLayerError(
            f"Local scratch database not found at {path}. Stage demo.db, or "
            "configure Snowflake (SNOWFLAKE_PAT)."
        )
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_flagged_encounters(config: Config) -> list[dict[str, Any]]:
    if _use_sqlite(config):
        conn = _sqlite_connection(config)
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT * FROM flagged_encounters")
            except sqlite3.OperationalError:
                cur.execute("SELECT * FROM encounters WHERE status = 'flagged'")
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
        return [_normalize_row(r) for r in rows]
    return [
        _normalize_row(r) for r in _sf_query(config, "SELECT * FROM flagged_encounters")
    ]


def get_encounter(config: Config, encounter_id: str) -> dict[str, Any] | None:
    for enc in get_flagged_encounters(config):
        if str(enc.get("encounter_id")) == str(encounter_id):
            return enc
    return None


def get_audit_log(config: Config) -> list[dict[str, Any]]:
    # audit_log schema (system of record): ID, ENCOUNTER_ID, ACTION, ACTOR,
    # DETAIL, CREATED_AT. Order newest-first by CREATED_AT.
    if _use_sqlite(config):
        conn = _sqlite_connection(config)
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM audit_log ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    return _sf_query(config, "SELECT * FROM audit_log ORDER BY created_at DESC")


def _audit_detail(approved_code: str, rationale: str) -> str:
    """Compose the human-readable audit DETAIL string."""
    code_part = f"code={approved_code}" if approved_code else "no code change"
    return f"{code_part}; {rationale}".strip()


def write_back_correction(
    config: Config,
    encounter_id: str,
    approved_code: str,
    approver: str,
    rationale: str,
    action: str = "approve",
    new_status: str = "corrected",
) -> dict[str, Any]:
    """Persist an approved correction (or a flag) and append the audit entry.

    The audit_log table is action-oriented (ENCOUNTER_ID, ACTION, ACTOR, DETAIL);
    ID and CREATED_AT are generated by Snowflake (identity / default timestamp).
    """
    approved_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    detail = _audit_detail(approved_code, rationale)

    if _use_sqlite(config):
        backend = "sqlite"
        conn = _sqlite_connection(config)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE encounters
                   SET status = ?, approved_code = ?, approved_by = ?, approved_at = ?
                 WHERE encounter_id = ?
                """,
                (new_status, approved_code, approver, approved_at, encounter_id),
            )
            cur.execute(
                """
                INSERT INTO audit_log (encounter_id, action, actor, detail, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (encounter_id, action, approver, detail, approved_at),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            raise DataLayerError(f"SQLite write-back failed: {exc}") from exc
        finally:
            conn.close()
    else:
        backend = "snowflake"
        conn = _snowflake_connection(config)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE encounters
                   SET status = %(status)s,
                       approved_code = %(approved_code)s,
                       approved_by = %(approver)s,
                       approved_at = %(approved_at)s
                 WHERE encounter_id = %(encounter_id)s
                """,
                {
                    "status": new_status,
                    "approved_code": approved_code,
                    "approver": approver,
                    "approved_at": approved_at,
                    "encounter_id": encounter_id,
                },
            )
            # ID (identity) and CREATED_AT (default CURRENT_TIMESTAMP) auto-populate.
            cur.execute(
                """
                INSERT INTO audit_log (encounter_id, action, actor, detail)
                VALUES
                    (%(encounter_id)s, %(action)s, %(actor)s, %(detail)s)
                """,
                {
                    "encounter_id": encounter_id,
                    "action": action,
                    "actor": approver,
                    "detail": detail,
                },
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            raise DataLayerError(f"Snowflake write-back failed: {exc}") from exc
        finally:
            conn.close()

    return {
        "status": "written",
        "backend": backend,
        "audit_log_entry": {
            "encounter_id": encounter_id,
            "action": action,
            "actor": approver,
            "detail": detail,
            "approved_code": approved_code,
            "approved_at": approved_at,
            "encounter_status": new_status,
        },
    }


# SQL that restores the pristine demo baseline. Status is fully determined by
# flag_reason (rows with a flag_reason are 'flagged', the rest are 'clean'), and
# the approval/suggested columns are cleared. The audit_log is emptied.
_RESET_ENCOUNTERS_SQL = """
    UPDATE encounters
       SET status = CASE
                        WHEN flag_reason IS NOT NULL AND flag_reason <> ''
                        THEN 'flagged' ELSE 'clean'
                    END,
           approved_code = NULL,
           approved_by = NULL,
           approved_at = NULL,
           suggested_code = NULL,
           suggested_description = NULL,
           suggested_rationale = NULL,
           confidence_score = NULL
"""


def reset_demo(config: Config) -> dict[str, Any]:
    """Reset the demo to its pristine baseline.

    Restores every encounter's status from its flag_reason, clears all approval
    and suggested columns, and empties the audit_log. Safe to run repeatedly.
    Returns counts so the caller can confirm.
    """
    if _use_sqlite(config):
        backend = "sqlite"
        conn = _sqlite_connection(config)
        try:
            cur = conn.cursor()
            cur.execute(_RESET_ENCOUNTERS_SQL)
            cur.execute("DELETE FROM audit_log")
            conn.commit()
            flagged = cur.execute(
                "SELECT COUNT(*) FROM encounters WHERE status = 'flagged'"
            ).fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            raise DataLayerError(f"SQLite reset failed: {exc}") from exc
        finally:
            conn.close()
    else:
        backend = "snowflake"
        conn = _snowflake_connection(config)
        try:
            cur = conn.cursor()
            cur.execute(_RESET_ENCOUNTERS_SQL)
            cur.execute("DELETE FROM audit_log")
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM encounters WHERE status = 'flagged'")
            flagged = cur.fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            raise DataLayerError(f"Snowflake reset failed: {exc}") from exc
        finally:
            conn.close()

    return {"status": "reset", "backend": backend, "flagged_encounters": flagged}
