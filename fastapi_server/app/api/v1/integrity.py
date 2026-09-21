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
Clinical Data Integrity review API.

Endpoints that drive the review Custom Application:

* GET  /v1/integrity/encounters            — flagged encounters (list view)
* GET  /v1/integrity/encounters/{id}       — one encounter + agent suggestion
* POST /v1/integrity/encounters/{id}/approve — approve/override -> write-back + audit
* POST /v1/integrity/encounters/{id}/flag    — flag for further review (no code change)
* GET  /v1/integrity/audit                 — audit trail (governance view)

The write-back is the governed moment: only an explicit Approve/Override action
persists a correction, and every action appends an immutable audit_log row that
the UI surfaces back to the reviewer.
"""

from __future__ import annotations

import logging
from typing import Any

from datarobot.auth.session import AuthCtx
from datarobot.auth.typing import Metadata
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth.ctx import get_agent_headers, must_get_auth_ctx
from app.config import Config
from app.integrity import data_layer, encounter_chat, jsl_lookup

logger = logging.getLogger(__name__)
integrity_router = APIRouter(prefix="/integrity", tags=["Clinical Data Integrity"])


def _config() -> Config:
    return Config()


def _approver_from_request(request: Request, provided: str | None) -> str:
    """Resolve the approver identity: explicit value wins, else the DR user email."""
    if provided:
        return provided
    email = request.headers.get("X-USER-EMAIL")
    if email:
        return email
    return "unknown-reviewer"


def _suggestion_for(encounter: dict[str, Any], config: Config) -> dict[str, Any]:
    return jsl_lookup.lookup_correct_code(
        diagnosis_code=str(encounter.get("diagnosis_code") or ""),
        clinical_note_excerpt=str(encounter.get("clinical_note_excerpt") or ""),
        config=config,
    )


class EncounterSummary(BaseModel):
    patient_id: str | None = None
    encounter_id: str | None = None
    encounter_date: str | None = None
    diagnosis_code: str | None = None
    diagnosis_description: str | None = None
    clinical_note_excerpt: str | None = None
    flag_reason: str | None = None
    status: str | None = None


class EncounterDetail(EncounterSummary):
    suggestion: dict[str, Any]


class ApproveRequest(BaseModel):
    approver: str | None = None
    rationale: str | None = None
    # Override: supply a manual code instead of the agent's suggestion.
    override_code: str | None = None


class FlagRequest(BaseModel):
    approver: str | None = None
    reason: str | None = None


class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class EncounterChatRequest(BaseModel):
    question: str
    history: list[ChatTurn] = []


@integrity_router.get("/encounters", response_model=list[EncounterSummary])
def list_flagged_encounters() -> list[dict[str, Any]]:
    """Return the flagged encounters for the list view."""
    try:
        return data_layer.get_flagged_encounters(_config())
    except data_layer.DataLayerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@integrity_router.get("/encounters/{encounter_id}", response_model=EncounterDetail)
def get_encounter_detail(encounter_id: str) -> dict[str, Any]:
    """Return one encounter plus the agent's suggested correction + rationale."""
    config = _config()
    try:
        encounter = data_layer.get_encounter(config, encounter_id)
    except data_layer.DataLayerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if encounter is None:
        raise HTTPException(
            status_code=404, detail=f"Encounter {encounter_id} not found"
        )
    try:
        suggestion = _suggestion_for(encounter, config)
    except (jsl_lookup.JSLLookupError, data_layer.DataLayerError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {**encounter, "suggestion": suggestion}


@integrity_router.post("/encounters/{encounter_id}/approve")
def approve_correction(
    encounter_id: str, body: ApproveRequest, request: Request
) -> dict[str, Any]:
    """Approve (or override) a correction: write it back and log the audit entry."""
    config = _config()
    try:
        encounter = data_layer.get_encounter(config, encounter_id)
    except data_layer.DataLayerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if encounter is None:
        raise HTTPException(
            status_code=404, detail=f"Encounter {encounter_id} not found"
        )

    suggestion = _suggestion_for(encounter, config)
    approved_code = body.override_code or suggestion.get("suggested_code")
    if not approved_code:
        raise HTTPException(
            status_code=422,
            detail=(
                "No code to approve: no suggestion matched and no override_code was "
                "provided."
            ),
        )

    is_override = bool(body.override_code)
    action = "override" if is_override else "approve"
    rationale = body.rationale or suggestion.get("rationale") or ""
    if is_override:
        rationale = f"[manual override] {rationale}".strip()
    approver = _approver_from_request(request, body.approver)

    try:
        result = data_layer.write_back_correction(
            config,
            encounter_id=encounter_id,
            approved_code=str(approved_code),
            approver=approver,
            rationale=rationale,
            action=action,
            new_status="corrected",
        )
    except data_layer.DataLayerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return result


@integrity_router.post("/encounters/{encounter_id}/flag")
def flag_for_review(
    encounter_id: str, body: FlagRequest, request: Request
) -> dict[str, Any]:
    """Flag an encounter for further human review — no code correction is written."""
    config = _config()
    try:
        encounter = data_layer.get_encounter(config, encounter_id)
    except data_layer.DataLayerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if encounter is None:
        raise HTTPException(
            status_code=404, detail=f"Encounter {encounter_id} not found"
        )

    approver = _approver_from_request(request, body.approver)
    reason = body.reason or "Flagged for further review by coder."
    try:
        result = data_layer.write_back_correction(
            config,
            encounter_id=encounter_id,
            approved_code=str(encounter.get("diagnosis_code") or ""),
            approver=approver,
            rationale=f"[flagged for review] {reason}",
            action="flag",
            new_status="needs_review",
        )
    except data_layer.DataLayerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return result


@integrity_router.get("/audit")
def get_audit_trail() -> dict[str, Any]:
    """Return the audit trail entries for the governance view."""
    try:
        entries = data_layer.get_audit_log(_config())
    except data_layer.DataLayerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"audit_log": entries, "count": len(entries)}


@integrity_router.post("/reset")
def reset_demo() -> dict[str, Any]:
    """Reset the demo to its pristine baseline (for repeatable demos).

    Restores encounter statuses from flag_reason, clears approvals/suggestions,
    and empties the audit_log. Idempotent.
    """
    try:
        return data_layer.reset_demo(_config())
    except data_layer.DataLayerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@integrity_router.post("/encounters/{encounter_id}/chat")
def ask_about_encounter(
    encounter_id: str,
    body: EncounterChatRequest,
    request: Request,
    auth_ctx: AuthCtx[Metadata] = Depends(must_get_auth_ctx),
) -> dict[str, Any]:
    """Answer a question about this encounter, routed through the deployed agent.

    The question is sent to the agent deployment so DataRobot moderation guards
    (PII/PHI, prompt injection, token limits — see agent/moderation_config.yaml)
    run on the prompt and response. The chat is kept read-only by prompt: the
    only path to a correction remains the Approve / Override / Flag actions.
    """
    config = _config()
    try:
        encounter = data_layer.get_encounter(config, encounter_id)
    except data_layer.DataLayerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if encounter is None:
        raise HTTPException(
            status_code=404, detail=f"Encounter {encounter_id} not found"
        )

    try:
        suggestion = _suggestion_for(encounter, config)
    except (jsl_lookup.JSLLookupError, data_layer.DataLayerError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Forward the DataRobot auth context to the deployed agent, exactly like the
    # main chat path, so the agent authorizes the request the same way.
    agent_headers = get_agent_headers(request, auth_ctx, config.session_secret_key)

    try:
        answer = encounter_chat.answer_question(
            encounter=encounter,
            suggestion=suggestion,
            question=body.question,
            history=[{"role": t.role, "content": t.content} for t in body.history],
            config=config,
            agent_headers=agent_headers,
        )
    except encounter_chat.EncounterChatError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"answer": answer}
