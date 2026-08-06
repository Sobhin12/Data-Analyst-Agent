from agent.nodes.orchestrator import _recent_turns_context, build_single_question


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
