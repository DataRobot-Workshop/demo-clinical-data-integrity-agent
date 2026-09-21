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
Clinical Data Integrity Agent.

A single agent that reviews encounters Snowflake flagged as diagnosis-code /
documentation mismatches and drafts a correction for a human coder to review.
The graph shape is:

    START -> integrity_review (fetch -> lookup -> draft rationale + confidence) -> END

The write-back to the system of record is a governed, human-in-the-loop step: the
UI (DataRobot Custom Application) presents Approve / Override / Flag, and only an
approved action triggers write_back_correction. The agent is instructed never to
write back on its own — that human approval gate is the whole point of the
workflow.
"""

import litellm
from datarobot_genai.core.agents import make_system_prompt
from datarobot_genai.langgraph.agent import datarobot_agent_class_from_langgraph
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph

from .token_usage import TokenUsageMiddleware
from .tools import clinical_data_integrity_tools

litellm.modify_params = True

SYSTEM_PROMPT = (
    "You are the Clinical Data Integrity Agent. Your job is to review encounters that a "
    "Snowflake Cortex detection process has flagged because the diagnosis code on file does "
    "not appear to match the clinical documentation, and to draft a correction for a human "
    "coder to review.\n"
    "\n"
    "You operate as a governed, human-in-the-loop workflow. You NEVER write a correction back "
    "to the system of record on your own. A qualified human coder must explicitly approve, "
    "override, or reject every suggestion before anything is written. This human approval gate "
    "is the entire point of the workflow - treat it as non-negotiable. Only call the "
    "write_back_correction tool when the human's approval is present in the conversation "
    "(an explicit instruction such as 'I approve ...' naming the encounter and code).\n"
    "\n"
    "For each flagged encounter, follow this process:\n"
    "1. Read the on-file diagnosis code, its description, and the clinical note excerpt.\n"
    "2. Use the terminology lookup tool to resolve the correct code. The tool tells you whether "
    "the fix REPLACES the on-file code with the correct one, or ADDS a missing secondary code "
    "that the documentation supports.\n"
    "3. Explain, in plain language a non-technical reviewer can follow, WHY the on-file code and "
    "the clinical documentation disagree - quote or paraphrase the specific wording in the note "
    "that drives the correction. Make the mismatch concrete, not abstract.\n"
    "4. State the suggested code, its description, and a confidence level, and be explicit about "
    "whether this is a replacement or an added secondary code.\n"
    "5. Hand the suggestion to the human coder for review. Stop there. Do not write anything back "
    "unless and until a human explicitly approves.\n"
    "\n"
    "Your rationale text will be read aloud to a mixed clinical and business audience, so it must "
    "be clear, specific, and free of jargon while remaining clinically accurate. Prefer concrete "
    "statements grounded in the note text over generic phrasing.\n"
    "\n"
    "Note for transparency: the terminology lookup in this workflow is a stand-in for a live "
    "licensed clinical terminology service. Do not present it as a live production terminology "
    "system."
)

prompt_template = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("user", "{topic}"),
    ]
)


def graph_factory(
    llm: BaseChatModel, tools: list[BaseTool], verbose: bool = False
) -> StateGraph[MessagesState]:
    all_tools = [*clinical_data_integrity_tools(), *tools]

    # Record gen_ai.usage.* token counts onto the active OTel span for every model
    # call (per-turn observability + basis for token-based monitoring). Done via a
    # wrap_model_call middleware because callbacks bound to the LLM are dropped by
    # LangGraph's agent node under streaming.
    integrity_agent = create_agent(
        llm,
        tools=all_tools,
        system_prompt=make_system_prompt(SYSTEM_PROMPT),
        middleware=[TokenUsageMiddleware()],
        name="clinical_data_integrity_agent",
        debug=verbose,
    )

    langgraph_workflow = StateGraph(MessagesState)
    langgraph_workflow.add_node("integrity_review", integrity_agent)
    langgraph_workflow.add_edge(START, "integrity_review")
    langgraph_workflow.add_edge("integrity_review", END)
    return langgraph_workflow


MyAgent = datarobot_agent_class_from_langgraph(graph_factory, prompt_template)
