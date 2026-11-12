from __future__ import annotations

import json
import math
import statistics
import time
from pathlib import Path
from typing import Any

from agent.pipeline import analyze_job
from agent.sample_data import jobs, portfolio_items
from rag.retriever import retrieve
from rag.verify import verify_claims

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "datasets" / "demo_dev.json"
OUTPUT = ROOT / "evals" / "results" / "demo_eval.json"
VARIANTS = ("V0", "V1", "V2", "V3", "V4", "V8")


def _dcg(relevance: list[int], limit: int = 10) -> float:
    return sum(value / math.log2(index + 2) for index, value in enumerate(relevance[:limit]))


def _retrieval_metrics(ranked_ids: list[str], gold_ids: list[str]) -> dict[str, float]:
    if not gold_ids:
        return {"recall_at_5": 0.0, "mrr": 0.0, "ndcg_at_10": 0.0}
    gold = set(gold_ids)
    relevant = [1 if item in gold else 0 for item in ranked_ids]
    reciprocal_rank = next((1 / (i + 1) for i, value in enumerate(relevant) if value), 0.0)
    ideal = _dcg([1] * min(len(gold), 10))
    return {
        "recall_at_5": len(set(ranked_ids[:5]) & gold) / len(gold),
        "mrr": reciprocal_rank,
        "ndcg_at_10": _dcg(relevant, 10) / ideal if ideal else 0.0,
    }


def _binary_metrics(expected: list[bool], predicted: list[bool]) -> dict[str, float]:
    tp = sum(actual and guess for actual, guess in zip(expected, predicted))
    fp = sum(not actual and guess for actual, guess in zip(expected, predicted))
    fn = sum(actual and not guess for actual, guess in zip(expected, predicted))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def run() -> dict[str, Any]:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    sample_jobs = {job["job_id"]: job for job in jobs()}
    evidence = [
        item for item in portfolio_items() if item["evidence_id"] == "evidence-001"
    ]
    records: dict[str, list[dict[str, Any]]] = {name: [] for name in VARIANTS}
    latencies: list[float] = []
    unsupported_before: list[int] = []
    unsupported_after: list[int] = []
    predicted_bid, expected_bid = [], []
    predicted_risk, expected_risk = [], []

    for item in dataset["items"]:
        job = sample_jobs[item["job_id"]]
        predicted = analyze_job(job)
        expected_bid.append(item["gold_decision"] == "bid")
        predicted_bid.append(predicted["decision"]["action"] == "bid")
        expected_risk.append(item["expected_risk"])
        predicted_risk.append(predicted["risk_report"]["score"] >= 0.7)
        if item["gold_evidence_ids"]:
            for variant in VARIANTS:
                start = time.perf_counter()
                ranked = retrieve(
                    variant,
                    item["query"] if variant != "V1" else " ".join(item["requirements"]),
                    evidence,
                    k=5,
                    requirements=item["requirements"],
                )
                latencies.append((time.perf_counter() - start) * 1000)
                ranked_ids = [str(row[0]["evidence_id"]) for row in ranked]
                records[variant].append(_retrieval_metrics(ranked_ids, item["gold_evidence_ids"]))
            checks = predicted["claim_verification"]
            unsupported_before.append(sum(check["status"] != "supported" for check in checks))
            final_checks = verify_claims(
                predicted["proposal_draft"]["cover_letter"],
                predicted["evidence"],
            )
            unsupported_after.append(sum(check["status"] != "supported" for check in final_checks))

    variant_results = {}
    for variant, values in records.items():
        variant_results[variant] = {
            metric: statistics.mean(result[metric] for result in values) if values else None
            for metric in ("recall_at_5", "mrr", "ndcg_at_10")
        }
        variant_results[variant]["queries"] = len(values)
    result = {
        "evaluation": "GigBid local sample smoke evaluation",
        "dataset": str(DATASET.relative_to(ROOT)).replace("\\", "/"),
        "dataset_type": dataset["dataset_type"],
        "hypothesis": dataset["hypothesis"],
        "total_jobs": len(dataset["items"]),
        "retrieval_query_count": len(records["V0"]),
        "retrieval_variants": variant_results,
        "decisions": {
            "bid_or_skip": _binary_metrics(expected_bid, predicted_bid),
            "scam_detection": _binary_metrics(expected_risk, predicted_risk),
        },
        "claim_verification": {
            "proposal_count": len(unsupported_before),
            "unsupported_claims_before_per_proposal": statistics.mean(unsupported_before)
            if unsupported_before
            else None,
            "unsupported_claims_after_per_proposal": statistics.mean(unsupported_after)
            if unsupported_after
            else None,
        },
        "marketplace_outcomes": {
            "reply_rate": None,
            "hire_rate": None,
            "reason": (
                "This baseline smoke runner has no marketplace outcome simulation; "
                "see gigsim_eval.json for separately generated synthetic outcomes."
            ),
        },
        "latency": {
            "retrieval_p95_ms": sorted(latencies)[max(0, math.ceil(0.95 * len(latencies)) - 1)]
            if latencies
            else None,
            "measurement_count": len(latencies),
            "scope": "In-process retrieval only; not end-to-end API or graph latency.",
        },
        "limitations": [
            "Only two bundled illustrative synthetic jobs and one evidence item are used in this baseline smoke evaluation.",
            "This smoke set is not the instructor-provided per-persona development set.",
            "The retrieval baseline is token-vector cosine, not a neural dense embedding.",
            "No outcome simulation, LLM judge, human panel, paid API, or live marketplace is run by this baseline evaluation.",
        ],
    }
    result["quality_gates"] = {
        "bid_or_skip_f1_at_least_0_90": result["decisions"]["bid_or_skip"]["f1"] >= 0.90,
        "scam_detection_f1_at_least_0_90": result["decisions"]["scam_detection"]["f1"] >= 0.90,
        "unsupported_claims_after_equal_zero": result["claim_verification"][
            "unsupported_claims_after_per_proposal"
        ]
        == 0,
    }
    result["quality_gates"]["passed"] = all(result["quality_gates"].values())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    result = run()
    print(json.dumps(result, indent=2))
    if not result["quality_gates"]["passed"]:
        raise SystemExit("Local evaluation quality gate failed; inspect the JSON results.")


if __name__ == "__main__":
    main()
