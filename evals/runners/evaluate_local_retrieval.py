"""Compare the implemented retrieval variants on fixed local relevance labels."""

import json
from statistics import mean

from agent.sample_data import portfolio_items
from agent.settings import ROOT
from evals.runners.evaluate_local_dev import DATASET
from evals.runners.run_demo_eval import VARIANTS, _retrieval_metrics
from rag.retriever import retrieve


def main():
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    corpus = portfolio_items()
    cases = dataset["items"]
    variants = {}
    for variant in VARIANTS:
        rows = []
        for item in cases:
            job = item["job"]
            persona = item["persona_id"]
            evidence = [entry for entry in corpus if entry["freelancer_id"] == persona]
            ranked = retrieve(
                variant, job["description"], evidence, k=10, requirements=job["required_skills"]
            )
            ids = [entry["evidence_id"] for entry, _ in ranked]
            rows.append(
                {
                    "job_id": job["job_id"],
                    "persona_id": persona,
                    "condition": item["condition"],
                    **_retrieval_metrics(ids, item["gold_evidence_ids"]),
                }
            )
        variants[variant] = {
            "overall": aggregate(rows),
            "by_persona": {
                persona: aggregate([row for row in rows if row["persona_id"] == persona])
                for persona in sorted({row["persona_id"] for row in rows})
            },
            "by_condition": {
                condition: aggregate([row for row in rows if row["condition"] == condition])
                for condition in sorted({row["condition"] for row in rows})
            },
        }
    result = {
        "provenance": dataset["provenance"],
        "hypothesis": "Requirement decomposition improves mean reciprocal rank over V0.",
        "cases": len(cases),
        "variants": variants,
    }
    output = ROOT / "evals" / "results" / "local_dev_retrieval.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: group["overall"] for name, group in variants.items()}, indent=2))


def aggregate(rows):
    return {
        metric: mean(row[metric] for row in rows) for metric in ("recall_at_5", "mrr", "ndcg_at_10")
    }


if __name__ == "__main__":
    main()
