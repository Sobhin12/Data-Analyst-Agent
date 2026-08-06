"""Full eval suite runner. See docs/text_to_sql_agent_design_spec.md §11.

Needs a real LLM configured (config.LLM_PROVIDER + matching API key) --
this drives the actual agent end-to-end for every gold question, then scores
it with both execution_accuracy (objective) and llm_judge (subjective).

Questions run strictly sequentially, on purpose -- never concurrently. A
provider's per-minute request/token limits apply across the whole run
regardless of how the calls are shaped, and config.EVAL_CALL_DELAY_SECONDS
paces every individual call (agent-internal and judge) to stay under them.

    python -m eval.run_eval
    python -m eval.run_eval -n 5   # only run the first 5 gold questions
"""

import argparse
import logging
import time
import uuid

import config
from agent.graph import build_graph
from agent.logging_config import configure_logging
from db.loader import get_engine
from eval.execution_accuracy import execution_accuracy
from eval.gold_questions import GOLD_QUESTIONS
from eval.llm_judge import llm_judge
from main import _fresh_turn_input

logger = logging.getLogger(__name__)


def run_full_eval(questions=GOLD_QUESTIONS):
    graph = build_graph()
    engine = get_engine()
    results = []

    for i, q in enumerate(questions):
        if i > 0:
            time.sleep(config.EVAL_CALL_DELAY_SECONDS)

        logger.info("eval: running question %r", q["question"])
        thread_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        response = graph.invoke(_fresh_turn_input(q["question"]), thread_config)

        sub_queries = response.get("sub_queries") or []
        first = sub_queries[0] if sub_queries else None

        # Execution accuracy only makes sense for single-query gold answers --
        # a trend gold question checks min_rows instead, and a multi-sub-query
        # agent answer would need to be compared as a set, not sub_queries[0].
        exec_acc = None
        if first and first.sql and q["type"] != "trend":
            try:
                exec_acc = execution_accuracy(first.sql, q["gold_sql"], engine)
            except Exception:
                exec_acc = False

        time.sleep(config.EVAL_CALL_DELAY_SECONDS)
        judge_scores = llm_judge(
            question=q["question"],
            gold_answer=q.get("gold_answer"),
            agent_response=response.get("final_report"),
            raw_data=first.result.rows if first and first.result else None,
        )

        logger.info(
            "eval: question %r -> exec_accurate=%s sub_queries=%d tool_calls=%s",
            q["question"], exec_acc, len(sub_queries), response.get("total_tool_calls"),
        )

        results.append(
            {
                "question": q["question"],
                "execution_accurate": exec_acc,
                "sub_query_count": len(sub_queries),
                "sql_retry_count": first.sql_retry_count if first else None,
                "total_tool_calls": response.get("total_tool_calls"),
                "clarification_fired": response.get("ambiguity_type") != "clear",
                **judge_scores,
            }
        )

    return results


def _print_summary(results: list[dict]) -> None:
    checked = [r for r in results if r["execution_accurate"] is not None]
    accurate = [r for r in checked if r["execution_accurate"]]
    if checked:
        print(f"Execution accuracy: {len(accurate)}/{len(checked)}")

    first_attempt = sum(1 for r in results if r["sql_retry_count"] == 0)
    print(f"First-attempt success: {first_attempt}/{len(results)}")

    print("LLM judge scores (avg/5):")
    for metric in ("accuracy", "faithfulness", "clarity", "completeness", "appropriate_refusal", "overall"):
        avg = sum(r.get(metric, 0) for r in results) / len(results)
        print(f"  {metric}: {avg:.2f}/5 ({avg / 5:.0%})")

    print()
    for r in results:
        mark = "✓" if r["execution_accurate"] else ("?" if r["execution_accurate"] is None else "✗")
        print(f"{mark} {r['question']} (retries={r['sql_retry_count']}, tool_calls={r['total_tool_calls']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the gold-question eval suite.")
    parser.add_argument(
        "-n", "--limit", type=int, default=None,
        help="Only run the first N gold questions (default: all %d)" % len(GOLD_QUESTIONS),
    )
    args = parser.parse_args()

    configure_logging()
    questions = GOLD_QUESTIONS[: args.limit] if args.limit else GOLD_QUESTIONS
    results = run_full_eval(questions)
    _print_summary(results)
