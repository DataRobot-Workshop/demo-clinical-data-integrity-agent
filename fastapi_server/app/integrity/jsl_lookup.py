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
Stand-in for a licensed clinical terminology server (John Snow Labs).

Backend copy of the JSL keyword-matching lookup. Snowflake is the system of
record: by default this reads `SELECT * FROM jsl_stand_in_lookup` and matches in
Python. The bundled jsl_stand_in_lookup.json is an opt-in local fallback gated by
USE_LOCAL_SQLITE, not the default read path. This is a workshop stand-in, not a
live terminology service, and the UI copy says so.

The MCP server and the agent have independent dependencies, so the backend keeps
its own self-contained copy rather than importing from agent/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import Config
from app.integrity.data_layer import _snowflake_connection, _use_sqlite

_DEFAULT_LOOKUP_FILENAME = "jsl_stand_in_lookup.json"

_RULE_COLUMNS = [
    "match_keywords",
    "action",
    "suggested_code",
    "suggested_description",
    "rationale",
    "confidence",
]


class JSLLookupError(RuntimeError):
    """Raised when the JSL stand-in rule set cannot be loaded."""


def _project_root() -> Path:
    # fastapi_server/app/integrity/jsl_lookup.py
    #   -> integrity -> app -> fastapi_server -> <root>
    return Path(__file__).resolve().parents[3]


def _lookup_path() -> Path:
    return _project_root() / _DEFAULT_LOOKUP_FILENAME


def _coerce_keywords(value: Any) -> list[str]:
    """Normalize match_keywords from Snowflake (VARIANT/string) or JSON (list)."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(k) for k in value]
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(k) for k in parsed]
            except json.JSONDecodeError:
                pass
        for sep in (";", "|", ","):
            if sep in text:
                return [part.strip() for part in text.split(sep) if part.strip()]
        return [text] if text else []
    return [str(value)]


def _normalize_rule(row: dict[str, Any]) -> dict[str, Any]:
    lowered = {str(k).lower(): v for k, v in row.items()}
    rule: dict[str, Any] = {col: lowered.get(col) for col in _RULE_COLUMNS}
    rule["match_keywords"] = _coerce_keywords(rule.get("match_keywords"))
    raw_confidence = rule.get("confidence")
    if raw_confidence is not None:
        try:
            rule["confidence"] = float(raw_confidence)
        except (TypeError, ValueError):
            rule["confidence"] = None
    return rule


def _load_rules_from_snowflake(config: Config) -> list[dict[str, Any]]:
    conn = _snowflake_connection(config)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM jsl_stand_in_lookup")
        col_names = [c[0].lower() for c in cur.description]
        rows = cur.fetchall()
    finally:
        conn.close()
    return [_normalize_rule(dict(zip(col_names, row))) for row in rows]


def _load_rules_from_json() -> list[dict[str, Any]]:
    path = _lookup_path()
    if not path.exists():
        raise JSLLookupError(
            f"JSL stand-in rule set not found at {path}. Stage "
            f"{_DEFAULT_LOOKUP_FILENAME} into the project root, or configure "
            "Snowflake (SNOWFLAKE_PAT)."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data["rules"] if isinstance(data, dict) and "rules" in data else data
    if not isinstance(rules, list):
        raise JSLLookupError(f"Expected a list of rules in {path}.")
    return [_normalize_rule(r) for r in rules]


def _load_rules(config: Config) -> list[dict[str, Any]]:
    """Snowflake by default; local JSON only as an opt-in fallback."""
    if _use_sqlite(config):
        return _load_rules_from_json()
    return _load_rules_from_snowflake(config)


def lookup_correct_code(
    diagnosis_code: str,
    clinical_note_excerpt: str,
    config: Config | None = None,
) -> dict[str, Any]:
    """Resolve the correct code for a flagged encounter via keyword matching."""
    config = config or Config()
    note = (clinical_note_excerpt or "").lower()
    rules = _load_rules(config)

    best: dict[str, Any] | None = None
    best_hits = 0
    for rule in rules:
        keywords = [str(k).lower() for k in rule.get("match_keywords", [])]
        hits = sum(1 for kw in keywords if kw in note)
        if hits > best_hits:
            best_hits = hits
            best = rule

    if best is None or best_hits == 0:
        return {
            "match": False,
            "action": None,
            "suggested_code": None,
            "suggested_description": None,
            "rationale": (
                "No terminology rule matched this documentation; route to manual "
                "coder review."
            ),
            "confidence": 0.0,
            "source": "JSL stand-in (Snowflake rule table — not a live terminology service)",
        }

    return {
        "match": True,
        "action": best.get("action"),
        "suggested_code": best.get("suggested_code"),
        "suggested_description": best.get("suggested_description"),
        "rationale": best.get("rationale"),
        "confidence": best.get("confidence"),
        "source": "JSL stand-in (Snowflake rule table — not a live terminology service)",
    }
