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
"""Tests for the clinical data integrity tools, data layer, and JSL lookup."""

import json
import sqlite3
from pathlib import Path

import pytest

from agent import data_layer, jsl_lookup, tools
from agent.config import Config


@pytest.fixture
def scratch_db(tmp_path: Path) -> Path:
    db = tmp_path / "demo.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE encounters (
            patient_id TEXT, encounter_id TEXT, encounter_date TEXT,
            diagnosis_code TEXT, diagnosis_description TEXT,
            clinical_note_excerpt TEXT, flag_reason TEXT, status TEXT,
            approved_code TEXT, approved_by TEXT, approved_at TEXT
        );
        CREATE TABLE audit_log (
            audit_id TEXT, encounter_id TEXT, approved_code TEXT,
            approved_by TEXT, approved_at TEXT, rationale TEXT
        );
        INSERT INTO encounters
            (patient_id, encounter_id, encounter_date, diagnosis_code,
             diagnosis_description, clinical_note_excerpt, flag_reason, status)
        VALUES
            ('P1', 'ENC-1', '2026-01-01', 'A00', 'Cholera',
             'Patient presents with acute chest pain and dyspnea.',
             'semantic_llm_mismatch', 'flagged');
        """
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def jsl_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    rules = tmp_path / "jsl_stand_in_lookup.json"
    rules.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "match_keywords": ["chest pain", "dyspnea"],
                        "action": "replace",
                        "suggested_code": "I20.9",
                        "suggested_description": "Angina pectoris, unspecified",
                        "rationale": "Documentation describes cardiac chest pain.",
                        "confidence": 0.92,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(jsl_lookup, "_lookup_path", lambda: rules)
    return rules


def _sqlite_config(db: Path) -> Config:
    return Config(use_local_sqlite=True, local_sqlite_path=str(db))  # type: ignore[call-arg]


class TestJSLLookup:
    def test_matches_on_keywords(self, jsl_rules, tmp_path):
        # use_local_sqlite routes the JSL lookup to the local JSON fallback.
        config = Config(use_local_sqlite=True, local_sqlite_path=str(tmp_path / "x.db"))
        result = jsl_lookup.lookup_correct_code(
            "A00", "Acute chest pain and dyspnea on exertion.", config=config
        )
        assert result["match"] is True
        assert result["action"] == "replace"
        assert result["suggested_code"] == "I20.9"
        assert result["confidence"] == 0.92

    def test_no_match_returns_structured_result(self, jsl_rules, tmp_path):
        config = Config(use_local_sqlite=True, local_sqlite_path=str(tmp_path / "x.db"))
        result = jsl_lookup.lookup_correct_code(
            "A00", "Routine wellness visit.", config=config
        )
        assert result["match"] is False
        assert result["suggested_code"] is None

    def test_coerce_keywords_handles_snowflake_shapes(self):
        # Snowflake may return a JSON-array string or a delimited string.
        assert jsl_lookup._coerce_keywords('["chest pain","dyspnea"]') == [
            "chest pain",
            "dyspnea",
        ]
        assert jsl_lookup._coerce_keywords("chest pain, dyspnea") == [
            "chest pain",
            "dyspnea",
        ]
        assert jsl_lookup._coerce_keywords(["a", "b"]) == ["a", "b"]
        assert jsl_lookup._coerce_keywords(None) == []


class TestDataLayer:
    def test_get_flagged_encounters(self, scratch_db):
        config = _sqlite_config(scratch_db)
        rows = data_layer.get_flagged_encounters(config)
        assert len(rows) == 1
        assert rows[0]["encounter_id"] == "ENC-1"
        assert rows[0]["status"] == "flagged"

    def test_write_back_updates_and_audits(self, scratch_db):
        config = _sqlite_config(scratch_db)
        result = data_layer.write_back_correction(
            encounter_id="ENC-1",
            approved_code="I20.9",
            approver="j.rivera",
            rationale="Approved cardiac code.",
            config=config,
        )
        assert result["status"] == "written"
        assert result["audit_log_entry"]["approved_code"] == "I20.9"

        audit = data_layer.get_audit_log(config)
        assert len(audit) == 1
        assert audit[0]["approved_by"] == "j.rivera"

        conn = sqlite3.connect(str(scratch_db))
        status = conn.execute(
            "SELECT status FROM encounters WHERE encounter_id = 'ENC-1'"
        ).fetchone()[0]
        conn.close()
        assert status == "corrected"


class TestTools:
    def test_get_flagged_encounters_tool(self, scratch_db, monkeypatch):
        config = _sqlite_config(scratch_db)
        monkeypatch.setattr(data_layer, "Config", lambda: config)
        payload = json.loads(tools.get_flagged_encounters.invoke({}))
        assert payload["count"] == 1

    def test_lookup_correct_code_tool(self, jsl_rules, tmp_path, monkeypatch):
        config = Config(use_local_sqlite=True, local_sqlite_path=str(tmp_path / "x.db"))
        monkeypatch.setattr(jsl_lookup, "Config", lambda: config)
        payload = json.loads(
            tools.lookup_correct_code.invoke(
                {
                    "diagnosis_code": "A00",
                    "clinical_note_excerpt": "chest pain, dyspnea",
                }
            )
        )
        assert payload["suggestion"]["suggested_code"] == "I20.9"

    def test_write_back_tool(self, scratch_db, monkeypatch):
        config = _sqlite_config(scratch_db)
        monkeypatch.setattr(data_layer, "Config", lambda: config)
        payload = json.loads(
            tools.write_back_correction.invoke(
                {
                    "encounter_id": "ENC-1",
                    "approved_code": "I20.9",
                    "approver": "j.rivera",
                    "rationale": "ok",
                }
            )
        )
        assert payload["result"]["status"] == "written"
