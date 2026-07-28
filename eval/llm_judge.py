"""LLM-as-judge scorer for final report quality.
See docs/text_to_sql_agent_design_spec.md §11.

Requires a real LLM (config.LLM_PROVIDER / the matching API key) -- there is
no offline path for this one, unlike execution_accuracy.
"""

from agent.llm import get_llm, parse_json_response

_JUDGE_PROMPT = """You are an evaluator for a text-to-SQL agent system.

Score the agent's response on the following criteria (1-5 each):

1. ACCURACY: Does the data in the response match the correct answer?
2. FAITHFULNESS: Does the explanation accurately reflect the data (no invented numbers)?
3. CLARITY: Is the explanation understandable to a non-technical user?
4. COMPLETENESS: Does the response fully answer the original question?
5. APPROPRIATE_REFUSAL: If data was unavailable, did the agent say so clearly?

Original question: {question}
Correct answer: {gold_answer}
Agent response: {agent_response}
Data returned by SQL: {raw_data}

Respond in JSON only, no other text:
{{
  "accuracy": 1,
  "faithfulness": 1,
  "clarity": 1,
  "completeness": 1,
  "appropriate_refusal": 1,
  "overall": 1,
  "reasoning": "one sentence explanation"
}}
"""


def llm_judge(question: str, gold_answer, agent_response: str, raw_data) -> dict:
    llm = get_llm(json_mode=True)
    prompt = _JUDGE_PROMPT.format(
        question=question,
        gold_answer=gold_answer,
        agent_response=agent_response,
        raw_data=raw_data,
    )
    response = llm.invoke(prompt)
    return parse_json_response(response.content)
