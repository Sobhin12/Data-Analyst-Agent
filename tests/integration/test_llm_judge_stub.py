"""Verifies llm_judge's prompt construction and JSON parsing without a real
API call -- the scoring itself obviously needs a real judge model, but the
plumbing (prompt fill-in, response parsing) doesn't."""

from unittest.mock import patch

from langchain_core.messages import AIMessage

from eval import llm_judge as llm_judge_module


class StubJudge:
    def invoke(self, prompt):
        assert "total revenue" in prompt  # question actually reached the prompt
        return AIMessage(
            content='{"accuracy": 5, "faithfulness": 5, "clarity": 4, '
            '"completeness": 5, "appropriate_refusal": 5, "overall": 5, '
            '"reasoning": "matches exactly"}'
        )


def test_llm_judge_parses_scores_from_response():
    with patch.object(llm_judge_module, "get_llm", return_value=StubJudge()):
        scores = llm_judge_module.llm_judge(
            question="What is the total revenue this quarter?",
            gold_answer=2328.6,
            agent_response="Total revenue: $2328.60",
            raw_data=[(2328.6,)],
        )

    assert scores["accuracy"] == 5
    assert scores["overall"] == 5
    assert "reasoning" in scores
