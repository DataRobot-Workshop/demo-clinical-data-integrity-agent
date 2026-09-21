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
Tools for the Clinical Data Integrity Agent.

Three tools implement the closed loop:

* get_flagged_encounters  — read encounters Snowflake flagged as code/doc mismatch.
* lookup_correct_code     — resolve the correct code via the JSL stand-in.
* write_back_correction   — persist an approved correction + audit trail entry.

write_back_correction is the only tool that mutates the system of record. It is
deliberately gated behind an explicit human-approval step in the graph (see
myagent.py); the agent must never call it without a coder's approval.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from . import data_layer, jsl_lookup


@tool
def get_flagged_encounters() -> str:
    """Return the encounters that were flagged because the diagnosis code on file
    does not match the clinical documentation.

    Reads `SELECT * FROM flagged_encounters` from the system of record (Snowflake).
    Each encounter includes: patient_id, encounter_id, encounter_date,
    diagnosis_code, diagnosis_description, clinical_note_excerpt, flag_reason,
    and status. Use this first to see what needs review.
    """
    try:
        encounters = data_layer.get_flagged_encounters()
    except data_layer.DataLayerError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"flagged_encounters": encounters, "count": len(encounters)})


@tool
def lookup_correct_code(diagnosis_code: str, clinical_note_excerpt: str) -> str:
    """Resolve the clinically correct diagnosis code for a flagged encounter.

    Given the on-file diagnosis_code and the clinical_note_excerpt, this queries a
    stand-in for a licensed clinical terminology service (John Snow Labs). It
    returns the recommended `action` ('replace' to swap the on-file code, or
    'add_secondary' to add a missing secondary code the documentation supports),
    the `suggested_code`, `suggested_description`, a `rationale`, and a
    `confidence` score.

    NOTE: this lookup is a workshop stand-in, not a live terminology system. Do
    not present it as a production terminology service.
    """
    try:
        result = jsl_lookup.lookup_correct_code(diagnosis_code, clinical_note_excerpt)
    except (jsl_lookup.JSLLookupError, data_layer.DataLayerError) as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"suggestion": result})


@tool
def write_back_correction(
    encounter_id: str, approved_code: str, approver: str, rationale: str
) -> str:
    """Write an APPROVED correction back to the system of record and log it.

    Only call this AFTER a human coder has explicitly approved the correction.
    It updates the encounter (status, approved_code, approved_by, approved_at)
    and appends an immutable audit_log entry recording who approved what, when,
    and why. Returns the audit entry that was created so it can be shown back to
    the reviewer.

    Args:
        encounter_id: the encounter being corrected.
        approved_code: the diagnosis code the human approved.
        approver: the name/id of the human coder who approved it.
        rationale: the reason recorded in the audit trail.
    """
    try:
        result = data_layer.write_back_correction(
            encounter_id=encounter_id,
            approved_code=approved_code,
            approver=approver,
            rationale=rationale,
        )
    except data_layer.DataLayerError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"result": result})


def clinical_data_integrity_tools() -> list[Any]:
    """Return the tool list for the Clinical Data Integrity Agent."""
    return [get_flagged_encounters, lookup_correct_code, write_back_correction]
