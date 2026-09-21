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
Encounter-scoped Q&A for the review UI, routed through the DEPLOYED agent.

Every question is sent to the agent deployment's DRAgent front server
(`{agent_endpoint}/generate/stream`), NOT directly to the LLM Gateway. This is
deliberate: routing through the deployed agent means the DataRobot
`datarobot_moderation` middleware runs on both the inbound prompt and the
outbound response, so the guards configured in agent/moderation_config.yaml
(PII/PHI detection, prompt injection, token limits) are enforced in production.
A direct LLM Gateway call would bypass all of that.

Read-only note: this path is kept advisory/read-only by PROMPT ONLY — the
system message below tells the agent not to write anything back and to direct
the user to the Approve/Override/Flag buttons. This is a softer guarantee than
structurally removing the write tool from the chat path; if adversarial testing
shows the prompt boundary can be bypassed, switch to a read-only tool set for
the chat context (conditional tool wiring in agent/agent/myagent.py's
graph_factory) rather than relying on the prompt.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from app.config import Config

READONLY_CONTEXT_PREAMBLE = (
    "You are answering a medical coder's question about ONE specific flagged "
    "encounter, shown below. Answer only about this encounter, grounded in the "
    "exact wording of its clinical note excerpt; quote the documentation that "
    "supports or contradicts a code.\n"
    "\n"
    "You are strictly READ-ONLY and advisory in this conversation. Do NOT call "
    "any tool that writes, approves, applies, or changes data, and do NOT claim "
    "to have done so. If the coder asks you to approve or write back a "
    "correction, explain that the write-back is a governed action that only "
    "happens when they click Approve / Override / Flag in the review UI, which "
    "records an audit-trail entry.\n"
)


class EncounterChatError(RuntimeError):
    """Raised when the encounter chat cannot produce a response."""


def _encounter_context(encounter: dict[str, Any], suggestion: dict[str, Any]) -> str:
    lines = [
        "FLAGGED ENCOUNTER UNDER REVIEW",
        f"- Encounter ID: {encounter.get('encounter_id')}",
        f"- Patient ID: {encounter.get('patient_id')}",
        f"- Encounter date: {encounter.get('encounter_date')}",
        f"- On-file diagnosis code: {encounter.get('diagnosis_code')}",
        f"- On-file description: {encounter.get('diagnosis_description')}",
        f"- Why it was flagged: {encounter.get('flag_reason')}",
        f"- Current status: {encounter.get('status')}",
        "",
        "CLINICAL NOTE EXCERPT (source of truth for documentation):",
        f'"""{encounter.get("clinical_note_excerpt")}"""',
        "",
        "TERMINOLOGY SUGGESTION (stand-in service, not authoritative):",
    ]
    if suggestion.get("match"):
        action = suggestion.get("action")
        action_text = (
            "REPLACE the on-file code"
            if action == "replace"
            else "ADD a missing secondary code"
        )
        lines += [
            f"- Recommended action: {action_text}",
            f"- Suggested code: {suggestion.get('suggested_code')}",
            f"- Suggested description: {suggestion.get('suggested_description')}",
            f"- Confidence: {suggestion.get('confidence')}",
            f"- Rationale: {suggestion.get('rationale')}",
        ]
    else:
        lines.append(
            "- No terminology rule matched this documentation; route to manual review."
        )
    return "\n".join(lines)


def _build_run_input(
    encounter: dict[str, Any],
    suggestion: dict[str, Any],
    question: str,
    history: list[dict[str, str]] | None,
) -> dict[str, Any]:
    """Build the AG-UI RunAgentInput body for the DRAgent /generate/stream call."""
    system_content = (
        READONLY_CONTEXT_PREAMBLE + "\n" + _encounter_context(encounter, suggestion)
    )
    messages: list[dict[str, Any]] = [
        {"id": str(uuid.uuid4()), "role": "system", "content": system_content},
    ]
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"id": str(uuid.uuid4()), "role": role, "content": content})
    messages.append({"id": str(uuid.uuid4()), "role": "user", "content": question})

    return {
        "thread_id": f"encounter-chat-{encounter.get('encounter_id')}",
        "run_id": str(uuid.uuid4()),
        "state": {},
        "messages": messages,
        "tools": [],
        "context": [],
        "forwarded_props": {},
    }


def answer_question(
    encounter: dict[str, Any],
    suggestion: dict[str, Any],
    question: str,
    history: list[dict[str, str]] | None = None,
    config: Config | None = None,
    agent_headers: dict[str, str] | None = None,
) -> str:
    """Answer a coder's question about this encounter via the deployed agent.

    Sends an AG-UI request to `{agent_endpoint}/generate/stream` and reconstructs
    the assistant text from the streamed TextMessageContent events. Because it
    goes through the deployed agent, moderation guards apply. If a guard blocks
    the prompt or response, the DRAgent server returns an error / content-filter
    event, which is surfaced to the caller.
    """
    config = config or Config()
    url = f"{config.agent_endpoint}/generate/stream"
    headers = {
        "Authorization": f"Bearer {config.datarobot_api_token}",
        "Content-Type": "application/json",
    }
    if agent_headers:
        headers.update(agent_headers)

    body = _build_run_input(encounter, suggestion, question, history)

    parts: list[str] = []
    error_message: str | None = None
    try:
        with httpx.Client(timeout=120.0) as client:
            with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code >= 400:
                    detail = response.read().decode(errors="replace")
                    raise EncounterChatError(
                        f"Agent deployment returned {response.status_code}: {detail}"
                    )
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:") :].strip()
                    if not payload:
                        continue
                    try:
                        raw = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    for event in raw.get("events", []) or []:
                        etype = event.get("type")
                        if etype in (
                            "TEXT_MESSAGE_CONTENT",
                            "TextMessageContent",
                        ):
                            delta = event.get("delta") or event.get("content")
                            if delta:
                                parts.append(delta)
                        elif etype in ("RUN_ERROR", "RunError"):
                            error_message = event.get("message") or "Agent run error."
    except EncounterChatError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise EncounterChatError(f"Agent request failed: {exc}") from exc

    if error_message:
        # Includes moderation blocks surfaced by the DRAgent server.
        raise EncounterChatError(error_message)

    answer = "".join(parts).strip()
    if not answer:
        raise EncounterChatError(
            "The agent returned no answer (it may have been blocked by a "
            "moderation guard)."
        )
    return answer
