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

from unittest.mock import Mock, patch

import pytest
from langchain_core.prompts import ChatPromptTemplate

from agent import MyAgent
from agent.myagent import graph_factory, prompt_template


class TestMyAgentLangGraph:
    @pytest.fixture
    def agent(self) -> MyAgent:
        mock_llm = Mock()
        return MyAgent(llm=mock_llm, verbose=True)

    def test_myagent_is_langgraph_agent_subclass(self):
        """Test that MyAgent inherits from LangGraphAgent."""
        from datarobot_genai.langgraph.agent import LangGraphAgent

        assert issubclass(MyAgent, LangGraphAgent)

    def test_init_with_llm(self):
        """Test initialization with an LLM instance."""
        mock_llm = Mock()
        agent = MyAgent(llm=mock_llm, verbose=True)
        assert agent.llm == mock_llm
        assert agent.verbose is True

    def test_prompt_template_is_chat_prompt(self):
        """Test that prompt_template is a ChatPromptTemplate."""
        assert isinstance(prompt_template, ChatPromptTemplate)

    def test_prompt_template_has_expected_variables(self):
        """Prior turns are replayed as native messages, so only `topic` is declared."""
        input_vars = prompt_template.input_variables
        assert "chat_history" not in input_vars
        assert "topic" in input_vars

    def test_prompt_template_formats_with_variables(self):
        """Test that prompt_template can be formatted with the topic variable."""
        messages = prompt_template.format_messages(topic="Review ENC-1004")
        assert len(messages) == 2
        assert "{topic}" not in messages[1].content
        assert "Review ENC-1004" in messages[1].content

    @patch("agent.myagent.create_agent")
    def test_graph_factory_creates_review_node(self, mock_create_agent):
        """graph_factory builds a single integrity_review node graph."""
        mock_llm = Mock()
        graph = graph_factory(mock_llm, [], verbose=False)
        assert graph is not None
        assert "integrity_review" in graph.nodes

    @patch("agent.myagent.create_agent")
    def test_graph_factory_includes_integrity_tools(self, mock_create_agent):
        """graph_factory wires the three clinical data integrity tools."""
        mock_llm = Mock()
        graph_factory(mock_llm, [], verbose=False)
        tool_names = {t.name for t in mock_create_agent.call_args[1]["tools"]}
        assert {
            "get_flagged_encounters",
            "lookup_correct_code",
            "write_back_correction",
        } <= tool_names

    @patch("agent.myagent.create_agent")
    def test_graph_factory_passes_extra_tools(self, mock_create_agent):
        """Extra (e.g. MCP) tools passed in are appended to the agent's tools."""
        mock_llm = Mock()
        extra = Mock()
        graph_factory(mock_llm, [extra], verbose=True)
        assert mock_create_agent.call_args[0][0] == mock_llm
        assert extra in mock_create_agent.call_args[1]["tools"]

    def test_workflow_property_uses_graph_factory(self, agent):
        """The agent's workflow property produces the review graph."""
        with patch("agent.myagent.create_agent"):
            workflow = agent.workflow
            assert workflow is not None
            assert "integrity_review" in workflow.nodes
