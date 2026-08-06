from unittest.mock import patch

from agent.nodes import orchestrator
from agent.nodes.orchestrator import _recent_turns_context, build_single_question, plan_initial
from agent.state import new_state


class _StubLLM:
    def __init__(self, content: str):
        self.content = content

    def invoke(self, prompt):
        from langchain_core.messages import AIMessage

        return AIMessage(content=self.content)


def test_build_single_question_offers_choices_not_open_text():
    question = build_single_question("period")
    assert "?" in question
    assert "[" in question  # offers concrete options, not an open-ended ask


def test_build_single_question_falls_back_for_unknown_param():
    question = build_single_question("gizmo_type")
    assert "gizmo_type" in question


def test_recent_turns_context_empty_when_no_history():
    assert "none" in _recent_turns_context([])


def test_recent_turns_context_includes_prior_query_and_result():
    history = [{"raw_query": "revenue for North region this quarter", "result_summary": "42.00"}]
    context = _recent_turns_context(history)
    assert "North region" in context
    assert "42.00" in context


def test_vague_intent_with_interpretations_sets_option_cards_not_text():
    plan = (
        '{"needs_clarification": true, "clarification_type": "vague_intent", '
        '"interpretations": ["Total sales", "Number of orders"], "reasoning": "ambiguous metric"}'
    )
    state = new_state("show me the best performers", "s1")
    with patch.object(orchestrator, "get_llm", return_value=_StubLLM(plan)):
        result = plan_initial(state)

    assert result["status"] == "awaiting_user"
    assert result["option_cards"] == [{"label": "Total sales"}, {"label": "Number of orders"}]
    assert not result.get("clarification_request")


def test_vague_intent_without_interpretations_falls_back_to_a_question():
    # The model flagged ambiguity but didn't name concrete options -- this
    # used to leave both clarification_request and option_cards empty, so
    # the frontend had nothing to display while still awaiting an answer.
    plan = (
        '{"needs_clarification": true, "clarification_type": "vague_intent", '
        '"interpretations": [], "reasoning": "the metric intended is unclear"}'
    )
    state = new_state("show me the best performers", "s1")
    with patch.object(orchestrator, "get_llm", return_value=_StubLLM(plan)):
        result = plan_initial(state)

    assert result["status"] == "awaiting_user"
    assert not result.get("option_cards")
    assert result["clarification_request"]  # never empty -- frontend always has something to show
