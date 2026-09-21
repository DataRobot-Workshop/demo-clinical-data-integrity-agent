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

JSL is a commercial product that is not stood up for this workshop, so the rule
set is a small keyword-matching table. Snowflake is the system of record for
these rules too: by default this reads `SELECT * FROM jsl_stand_in_lookup` and
keyword-matches the clinical note text in Python. The bundled
jsl_stand_in_lookup.json is an opt-in local fallback, gated by the same
USE_LOCAL_SQLITE toggle the data layer uses — not the default read path.

This is deliberately transparent: the agent's system prompt (and the UI copy)
say this is a stand-in, not a live terminology service.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Config
from .data_layer import _snowflake_connection, _use_sqlite

_DEFAULT_LOOKUP_FILENAME = "jsl_stand_in_lookup.json"

# Columns the jsl_stand_in_lookup table / JSON rules expose.
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
    # agent/agent/jsl_lookup.py -> agent/agent -> agent -> <root>
    return Path(__file__).resolve().parents[2]


def _lookup_path() -> Path:
    return _project_root() / _DEFAULT_LOOKUP_FILENAME


def _coerce_keywords(value: Any) -> list[str]:
    """Normalize match_keywords into a list of strings.

    Snowflake may return a JSON array (VARIANT), a delimited string, or a list;
    the JSON file returns a list. Handle all shapes.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(k) for k in value]
    if isinstance(value, str):
        text = value.strip()
        # Try JSON array first (e.g. '["chest pain","dyspnea"]').
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(k) for k in parsed]
            except json.JSONDecodeError:
                pass
        # Fall back to comma/semicolon/pipe separated values.
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


# ---------------------------------------------------------------------------
# Rule loading — Snowflake (default) or local JSON fallback
# ---------------------------------------------------------------------------
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
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise JSLLookupError(f"Could not parse {path}: {exc}") from exc

    rules = data["rules"] if isinstance(data, dict) and "rules" in data else data
    if not isinstance(rules, list):
        raise JSLLookupError(
            f"Expected a list of rules in {path}, got {type(rules).__name__}."
        )
    return [_normalize_rule(r) for r in rules]


def _load_rules(config: Config) -> list[dict[str, Any]]:
    """Load the terminology rules.

    Reads `SELECT * FROM jsl_stand_in_lookup` from Snowflake by default. The
    local JSON file is used only as an opt-in fallback when USE_LOCAL_SQLITE is
    set (or no PAT is configured) — the same toggle the data layer uses.
    """
    if _use_sqlite(config):
        return _load_rules_from_json()
    return _load_rules_from_snowflake(config)


def lookup_correct_code(
    diagnosis_code: str,
    clinical_note_excerpt: str,
    config: Config | None = None,
) -> dict[str, Any]:
    """Resolve the correct code for a flagged encounter.

    Matches the clinical note text against each rule's match_keywords (case
    insensitive). Returns the matching rule's action / suggested_code /
    suggested_description / rationale / confidence. When nothing matches, returns
    a structured "no_match" result so the agent can say so honestly rather than
    invent a code.
    """
    config = config or Config()
    note = (clinical_note_excerpt or "").lower()
    rules = _load_rules(config)

    best: dict[str, Any] | None = None
    best_hits = 0
    for rule in rules:
        keywords = [str(k).lower() for k in rule.get("match_keywords", [])]
        if not keywords:
            continue
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
                "No terminology rule matched this documentation. In production a "
                "live terminology service would be queried; for this workshop the "
                "stand-in has no rule for this note, so no automated suggestion is "
                "offered — route to manual coder review."
            ),
            "confidence": 0.0,
            "source": "JSL stand-in (Snowflake rule table — not a live terminology service)",
        }

    return {
        "match": True,
        "matched_diagnosis_code": diagnosis_code,
        "action": best.get("action"),
        "suggested_code": best.get("suggested_code"),
        "suggested_description": best.get("suggested_description"),
        "rationale": best.get("rationale"),
        "confidence": best.get("confidence"),
        "matched_keywords": [
            kw
            for kw in (str(k).lower() for k in best.get("match_keywords", []))
            if kw in note
        ],
        "source": "JSL stand-in (Snowflake rule table — not a live terminology service)",
    }
