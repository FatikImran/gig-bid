"""Run the labeled local benchmark in fixture mode or on both Groq models."""

import argparse
import json
import os
import tempfile
from math import ceil
from pathlib import Path
from statistics import mean

from agent.settings import ROOT, agent_config
from evals.runners.evaluate_open_models import MODELS, run_case, summarize
from evals.runners.run_demo_eval import _binary_metrics, _retrieval_metrics

DATASET = ROOT / "evals" / "datasets" / "local_dev.json"


def metrics(rows):
    risk_threshold = agent_config()["thresholds"]["maximum_risk_score"]
    retrieval = [
        _retrieval_metrics(row["ranked_evidence_ids"], row["gold_evidence_ids"]) for row in rows
    ]
    prices = [row for row in rows if row["fair_fixed_usd"]]
    latencies = sorted(row["latency_seconds"] for row in rows if row["approval_waiting"])
    claims = [
        row["unsupported_final_claims_by_heuristic"]
        for row in rows
        if row["approval_waiting"] and row["unsupported_final_claims_by_heuristic"] is not None
    ]
    return {
        **summarize(rows),
        "p95_approval_latency_seconds": latencies[ceil(0.95 * len(latencies)) - 1]
        if latencies
        else None,
        "prompt_tokens": sum(row["prompt_tokens"] for row in rows),
        "completion_tokens": sum(row["completion_tokens"] for row in rows),
        "mean_unsupported_final_claims_by_heuristic": mean(claims) if claims else None,
        "bid_detection": _binary_metrics(
            [row["expected_decision"] == "bid" for row in rows],
            [row["decision"] == "bid" for row in rows],
        ),
        "risk_detection": _binary_metrics(
            [row["expected_risk"] for row in rows],
            [row["risk_score"] >= risk_threshold for row in rows],
        ),
        "retrieval": {key: mean(item[key] for item in retrieval) for key in retrieval[0]},
        "prices_in_band": sum(
            row["price_usd"] is not None
            and row["fair_fixed_usd"][0] <= row["price_usd"] <= row["fair_fixed_usd"][1]
            for row in prices
        ),
        "priced_cases_expected": len(prices),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groq", action="store_true", help="Run both models on every case.")
    parser.add_argument(
        "--pilot", action="store_true", help="Use the first brief for each persona."
    )
    args = parser.parse_args()
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    items = dataset["items"]
    if args.pilot:
        first_brief = {}
        for item in items:
            first_brief.setdefault(
                item["persona_id"], item["job"]["job_id"].rsplit("-standard", 1)[0]
            )
        items = [
            item
            for item in items
            if item["job"]["job_id"].startswith(first_brief[item["persona_id"]] + "-")
        ]
    os.environ["GIGBID_MODEL_PROFILE"] = "open" if args.groq else "fixtures"
    os.environ["GIGBID_MODEL_PROVIDER"] = "groq" if args.groq else "local"
    reports = {}
    with tempfile.TemporaryDirectory() as directory:
        usage = Path(directory) / "usage.jsonl"
        os.environ["GIGBID_MODEL_USAGE_PATH"] = str(usage)
        for model in MODELS if args.groq else ("fixtures",):
            os.environ["GROQ_MODEL"] = model
            rows = []
            for item in items:
                print(f"{model} | {item['job']['job_id']}", flush=True)
                row = run_case(
                    item["job"],
                    item["gold_decision"],
                    model,
                    usage,
                    persona_id=item["persona_id"],
                    retry_rate_limits=args.groq,
                )
                rows.append({**item, **row})
            reports[model] = {
                "overall": metrics(rows),
                "by_persona": {
                    persona: metrics([row for row in rows if row["persona_id"] == persona])
                    for persona in sorted({row["persona_id"] for row in rows})
                },
                "runs": rows,
            }
    profile = "groq" if args.groq else "fixtures"
    subset = "_pilot" if args.pilot else ""
    output = ROOT / "evals" / "results" / f"local_dev_{profile}{subset}.json"
    output.write_text(
        json.dumps(
            {
                "provenance": dataset["provenance"],
                "hypothesis": dataset["hypothesis"],
                "decision_mapping": "Watch counts as a non-bid for bid detection.",
                "runs": reports,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({model: report["overall"] for model, report in reports.items()}, indent=2))


if __name__ == "__main__":
    main()
