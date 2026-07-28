from agent.nodes.clarification import (
    build_single_question,
    detect_missing_filter,
    memory_can_resolve,
)
from agent.state import new_state


def test_detect_missing_filter_period():
    assert detect_missing_filter("how about South region?", {"period": "Q2 2026"}) == "period"


def test_detect_missing_filter_region():
    assert (
        detect_missing_filter("what about last quarter?", {"region": "South"}) == "region"
    )


def test_detect_missing_filter_none_when_present():
    assert detect_missing_filter("revenue for Q2 2026", {"period": "Q2 2026"}) is None


def test_memory_can_resolve_matches_spec_cross_turn_example_turn_2():
    state = new_state("how about the South region?", "s1")
    state["active_filters"] = {"region": "North", "period": "Q2 2026"}
    state["turn_history"] = [{"raw_query": "revenue for North region this quarter"}]

    can_resolve, resolution = memory_can_resolve(state["raw_query"], state)

    assert can_resolve is True
    assert "Q2 2026" in resolution


def test_memory_can_resolve_matches_spec_cross_turn_example_turn_3():
    state = new_state("what about last quarter?", "s1")
    state["active_filters"] = {"region": "South", "period": "Q2 2026"}
    state["turn_history"] = [{"raw_query": "how about the South region?"}]

    can_resolve, resolution = memory_can_resolve(state["raw_query"], state)

    assert can_resolve is True
    assert "South" in resolution


def test_memory_can_resolve_false_with_no_history():
    state = new_state("show me sales", "s1")
    can_resolve, _ = memory_can_resolve(state["raw_query"], state)
    assert can_resolve is False


def test_build_single_question_offers_choices_not_open_text():
    question = build_single_question("period")
    assert "?" in question
    assert "[" in question  # offers concrete options, not an open-ended ask


def test_build_single_question_falls_back_for_unknown_param():
    question = build_single_question("gizmo_type")
    assert "gizmo_type" in question
