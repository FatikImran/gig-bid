"""Compare open-weight models on synthetic jobs through the approval gate."""

import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from agent.graphs.bid_graph import build_bid_graph
from agent.model_runtime import GroqInferenceError
from agent.sample_data import load_json
from agent.settings import ROOT
from rag.verify import verify_claims

MODELS = ("openai/gpt-oss-20b", "openai/gpt-oss-120b")
OUTPUT = ROOT / "evals" / "results" / "open_model_smoke.json"


def cases():
    churn, unpaid = load_json("jobs.json")
    threshold_review = {
        **churn,
        "job_id": "synthetic-threshold-review",
        "title": "Review thresholds for a binary classifier",
        "description": (
            "Use Python and scikit-learn to compare classification thresholds, "
            "report precision and recall, and summarize error analysis."
        ),
        "screening_questions": [],
    }
    low_budget = {
        **churn,
        "job_id": "synthetic-low-budget",
        "budget": {**churn["budget"], "min": 5, "max": 10},
    }
    return [(churn, "bid"), (unpaid, "skip"), (threshold_review, "bid"), (low_budget, "skip")]


def run_case(
    job,
    expected,
    model,
    usage_path,
    *,
    persona_id=None,
    retry_rate_limits=False,
    max_rate_limit_retries=1,
):
    usage_path.write_text("", encoding="utf-8")
    graph = build_bid_graph()
    config = {"configurable": {"thread_id": job["job_id"]}}
    started = time.perf_counter()
    error = None
    graph_input = {"job": job, "persona_id": persona_id}
    attempts = max_rate_limit_retries + 1 if retry_rate_limits else 1
    for attempt in range(attempts):
        try:
            graph.invoke(graph_input, config)
            break
        except GroqInferenceError as exc:
            print(f"  HTTP {exc.status_code}, retry-after: {exc.retry_after}", flush=True)
            retry_after = exc.retry_after or ""
            if (
                attempt + 1 < attempts
                and exc.status_code == 429
                and retry_after.isdecimal()
                and int(retry_after) <= 30
            ):
                time.sleep(int(retry_after) + 1)
                graph_input = None
                continue
            error = {"http_status": exc.status_code, "retry_after": exc.retry_after}
    snapshot = graph.get_state(config)
    state = snapshot.values
    approval_waiting = error is None and "approval" in snapshot.next
    elapsed = time.perf_counter() - started
    usage = [json.loads(line) for line in usage_path.read_text(encoding="utf-8").splitlines()]
    draft = state.get("proposal_draft") or {}
    text = draft.get("cover_letter", "")
    unsupported = (
        sum(
            claim["status"] != "supported"
            for claim in verify_claims(text, state.get("evidence", []))
        )
        if text
        else None
    )
    return {
        "job_id": job["job_id"],
        "model": model,
        "expected_decision": expected,
        "decision": state.get("decision", {}).get("action"),
        "risk_score": state.get("risk_report", {}).get("score"),
        "ranked_evidence_ids": [item["evidence_id"] for item in state.get("evidence", [])],
        "price_usd": state.get("price_quote", {}).get("amount"),
        "provider_error": error,
        "approval_waiting": approval_waiting,
        "latency_seconds": round(elapsed, 3),
        "revisions": state.get("revision_count"),
        "draft": draft or None,
        "unsupported_final_claims_by_heuristic": unsupported,
        "model_calls": len(usage),
        "prompt_tokens": sum(call["prompt_tokens"] for call in usage),
        "completion_tokens": sum(call["completion_tokens"] for call in usage),
        "estimated_api_usd": round(sum(call["api_usd"] for call in usage), 9),
    }


def summarize(rows):
    drafts = [row for row in rows if row["expected_decision"] == "bid"]
    approved = [row for row in drafts if row["approval_waiting"]]
    skips = [row for row in rows if row["expected_decision"] == "skip"]
    return {
        "cases": len(rows),
        "correct_decisions": sum(row["expected_decision"] == row["decision"] for row in rows),
        "draft_cases": len(drafts),
        "drafts_at_approval": len(approved),
        "provider_errors": sum(row["provider_error"] is not None for row in rows),
        "skip_cases_with_zero_model_calls": sum(row["model_calls"] == 0 for row in skips),
        "median_draft_latency_seconds": round(
            statistics.median(row["latency_seconds"] for row in approved), 3
        )
        if approved
        else None,
        "estimated_total_api_usd": round(sum(row["estimated_api_usd"] for row in rows), 9),
    }


def main():
    os.environ["GIGBID_MODEL_PROFILE"] = "open"
    os.environ["GIGBID_MODEL_PROVIDER"] = "groq"
    runs = []
    with tempfile.TemporaryDirectory() as directory:
        usage_path = Path(directory) / "usage.jsonl"
        env_name = "GIGBID_MODEL_USAGE_PATH"
        previous = os.environ.get(env_name)
        os.environ[env_name] = str(usage_path)
        try:
            for model in MODELS:
                os.environ["GROQ_MODEL"] = model
                for job, expected in cases():
                    print(f"{model} | {job['job_id']}", flush=True)
                    runs.append(run_case(job, expected, model, usage_path))
        finally:
            if previous is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = previous
    result = {
        "dataset": "Two bundled synthetic jobs and two variants, one pass per model.",
        "method": (
            "The decision uses shared rules. Only Writer and Critic use the model. "
            "Claim checks use the pipeline's heuristic verifier. "
            "Cost uses standard Groq token prices without caching discounts."
        ),
        "summary": {
            model: summarize([row for row in runs if row["model"] == model]) for model in MODELS
        },
        "runs": runs,
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
