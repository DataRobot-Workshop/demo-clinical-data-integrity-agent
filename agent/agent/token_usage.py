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
Token-usage tracing for the Clinical Data Integrity Agent.

The DataRobot LLM Gateway returns token usage on streamed responses, and the
LangChain LLM surfaces it as `usage_metadata` on the AI message (verified). This
middleware wraps every model call inside the agent and writes the resulting
input / output / total token counts onto the active OpenTelemetry span using
gen_ai.* semantic conventions, so per-turn token usage appears in DataRobot
traces and can back token-based monitoring.

We use AgentMiddleware.wrap_model_call rather than a plain LangChain callback:
callbacks bound with llm.with_config are dropped by LangGraph's agent node under
the astream(stream_mode=[...]) path (verified — on_llm_end never fired), whereas
wrap_model_call is invoked for every model call and receives the response
messages directly.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage
from opentelemetry import trace

logger = logging.getLogger(__name__)

_ATTR_INPUT = "gen_ai.usage.input_tokens"
_ATTR_OUTPUT = "gen_ai.usage.output_tokens"
_ATTR_TOTAL = "gen_ai.usage.total_tokens"
_ATTR_RUN_INPUT = "gen_ai.usage.run.input_tokens"
_ATTR_RUN_OUTPUT = "gen_ai.usage.run.output_tokens"
_ATTR_RUN_TOTAL = "gen_ai.usage.run.total_tokens"


def _usage_from_messages(messages: list[Any]) -> dict[str, int] | None:
    """Extract token usage from the AI message(s) returned by a model call."""
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        usage = getattr(message, "usage_metadata", None)
        if usage:
            in_tok = int(usage.get("input_tokens") or 0)
            out_tok = int(usage.get("output_tokens") or 0)
            return {
                "input": in_tok,
                "output": out_tok,
                "total": int(usage.get("total_tokens") or in_tok + out_tok),
            }
        # Fallback: some providers put usage under response_metadata.token_usage.
        token_usage = (getattr(message, "response_metadata", {}) or {}).get(
            "token_usage"
        )
        if token_usage:
            prompt = int(token_usage.get("prompt_tokens") or 0)
            completion = int(token_usage.get("completion_tokens") or 0)
            return {
                "input": prompt,
                "output": completion,
                "total": int(token_usage.get("total_tokens") or prompt + completion),
            }
    return None


class TokenUsageMiddleware(AgentMiddleware):
    """Records per-call and running token usage onto the active OTel span."""

    def __init__(self) -> None:
        super().__init__()
        self._run_input = 0
        self._run_output = 0
        self._run_total = 0

    def _record(self, usage: dict[str, int]) -> None:
        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return
        span.set_attribute(_ATTR_INPUT, usage["input"])
        span.set_attribute(_ATTR_OUTPUT, usage["output"])
        span.set_attribute(_ATTR_TOTAL, usage["total"])

        self._run_input += usage["input"]
        self._run_output += usage["output"]
        self._run_total += usage["total"]
        span.set_attribute(_ATTR_RUN_INPUT, self._run_input)
        span.set_attribute(_ATTR_RUN_OUTPUT, self._run_output)
        span.set_attribute(_ATTR_RUN_TOTAL, self._run_total)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        response = handler(request)
        try:
            usage = _usage_from_messages(getattr(response, "result", []) or [])
            if usage:
                self._record(usage)
        except Exception:  # noqa: BLE001 - tracing must never break the agent
            logger.debug("TokenUsageMiddleware failed to record usage", exc_info=True)
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Any],
    ) -> Any:
        response = await handler(request)
        try:
            usage = _usage_from_messages(getattr(response, "result", []) or [])
            if usage:
                self._record(usage)
        except Exception:  # noqa: BLE001
            logger.debug("TokenUsageMiddleware failed to record usage", exc_info=True)
        return response
