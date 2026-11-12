from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from agent.pipeline import analyze_job
from agent.sample_data import freelancers
from agent.settings import agent_config
from evals.runners.prepare_kaggle_data import _scenario_job, build_seed
from gigsim.app import ProposalSubmission, _outcome, load_seed

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "evals" / "results" / "gigsim_eval.json"
RAW_JOBS = ROOT / "data" / "raw" / "upwork-jobs.csv"
EVALUATION_POOL_LIMIT = 1000
HISTORICAL_POSTING_LIMIT = 50


def _rates(outcomes: list[str]) -> dict[str, float | int]:
    if not outcomes:
        return {"proposal_count": 0, "reply_rate": 0.0, "hire_rate": 0.0}
    return {
        "proposal_count": len(outcomes),
        "reply_rate": sum(outcome in {"replied", "hired"} for outcome in outcomes) / len(outcomes),
        "hire_rate": sum(outcome == "hired" for outcome in outcomes) / len(outcomes),
    }


def run() -> dict[str, Any]:
    if RAW_JOBS.is_file():
        with RAW_JOBS.open("r", encoding="utf-8-sig", newline="") as stream:
            seed = build_seed(
                list(csv.DictReader(stream)),
                limit=EVALUATION_POOL_LIMIT,
                synthetic_scenarios=40,
            )
        evaluation_source = "raw Kaggle postings, deterministic 1000-row capped sample"
    else:
        seed = load_seed()
        existing_scenarios = [
            job for job in seed["jobs"] if job.get("data_provenance") == "synthetic_scenario"
        ]
        if len(existing_scenarios) < 40:
            safe_base = next(
                (job for job in seed["jobs"] if not job.get("warning_signals")),
                seed["jobs"][0] if seed["jobs"] else None,
            )
        else:
            safe_base = None
        if safe_base is not None:
            scenario_types = ("unpaid_off_platform", "prompt_injection")
            seed["jobs"].extend(
                _scenario_job(safe_base, scenario_types[index % len(scenario_types)], index)
                for index in range(len(existing_scenarios), 40)
            )
        evaluation_source = "prepared local seed; raw Kaggle CSV unavailable"
    historical_postings = [
        job for job in seed["jobs"] if job.get("data_provenance") == "kaggle_posting"
    ]
    scenario_jobs = [
        job
        for job in seed["jobs"]
        if job.get("data_provenance") == "synthetic_scenario"
    ][:40]
    strategies: dict[str, dict[str, list[str]]] = {
        profile["freelancer_id"]: {"generic": [], "evidence_draft": []}
        for profile in freelancers()
    }
    decisions: list[dict[str, Any]] = []
    evaluated = []
    minimum_fit = float(agent_config()["thresholds"]["minimum_fit_score"])

    for job in historical_postings:
        if len(evaluated) >= HISTORICAL_POSTING_LIMIT:
            break
        skills = {str(skill).casefold() for skill in job.get("required_skills", [])}
        budget = job.get("budget") or {}
        candidates = []
        for profile in freelancers():
            profile_skills = {str(skill).casefold() for skill in profile.get("skills", [])}
            fit_score = len(skills & profile_skills) / max(1, len(skills))
            floor = (
                profile["hourly_rate_usd"]
                if budget.get("type") == "hourly"
                else profile["minimum_project_budget_usd"]
            )
            if fit_score >= minimum_fit and float(budget.get("max") or 0) >= floor:
                candidates.append((profile, fit_score))
        if not candidates:
            continue
        profile, _score = max(candidates, key=lambda pair: pair[1])
        analysis = analyze_job(job, profile["freelancer_id"])
        if analysis["decision"]["action"] == "bid":
            evaluated.append((job, profile, analysis))

    for job in scenario_jobs:
        analysis = analyze_job(job)
        decisions.append(
            {
                "expected_skip": True,
                "predicted_skip": analysis["decision"]["action"] == "skip",
                "scenario": job.get("synthetic_scenario"),
            }
        )

    for job, profile, analysis in evaluated:
        client = seed["clients"][job["client_id"]]
        evidence = analysis["evidence"]
        supported_draft = analysis["proposal_draft"]["cover_letter"]
        if not evidence or not supported_draft:
            continue
        amount = float(analysis["price_quote"]["amount"])
        variants = {
            "generic": "I am excited to apply. I am a skilled freelancer and can do this project.",
            "evidence_draft": supported_draft,
        }
        for strategy, cover_letter in variants.items():
            submission = ProposalSubmission(
                job_id=job["job_id"],
                client_id=job["client_id"],
                cover_letter=cover_letter,
                screening_answers=["I would validate the requested deliverables and report results."]
                if job.get("screening_questions")
                else [],
                evidence_ids=[str(item["evidence_id"]) for item in evidence],
                amount=amount,
                idempotency_key=f"eval-{strategy}-{job['job_id']}",
                approved=True,
            )
            strategies[profile["freelancer_id"]][strategy].append(_outcome(job, client, submission))

    missed = sum(not item["predicted_skip"] for item in decisions)
    result = {
        "evaluation": "GigBid local synthetic-client simulation",
        "dataset_type": "synthetic_outcomes_on_kaggle_derived_jobs",
        "evaluation_source": evaluation_source,
        "historical_postings_in_candidate_pool": len(historical_postings),
        "historical_postings_evaluated": len(evaluated),
        "synthetic_safety_scenarios_evaluated": len(decisions),
        "candidate_selection": (
            f"Up to {HISTORICAL_POSTING_LIMIT} first eligible postings in deterministic seed order; eligibility "
            "requires a bid decision for at least one synthetic persona."
        ),
        "simulated_proposal_outcomes_by_persona": {
            persona_id: {
                strategy: _rates(outcomes) for strategy, outcomes in variants.items()
            }
            for persona_id, variants in strategies.items()
        },
        "synthetic_scenario_skip_detection": {
            "scenario_count": len(decisions),
            "missed_skip_count": missed,
            "recall": (len(decisions) - missed) / len(decisions) if decisions else None,
        },
        "limitations": [
            "Client preferences and reply/hire outcomes are synthetic deterministic rules, not real client responses.",
            "Kaggle job postings are not labeled gold data for bid/skip or job risk.",
            (
                f"The candidate pool is a deterministic hash-ordered sample capped at "
                f"{EVALUATION_POOL_LIMIT} when the raw CSV is available, not a population sample."
            ),
            "The best-fitting eligible synthetic persona is selected per posting; this is not a user-persona choice study.",
            "All three synthetic personas and their authored synthetic portfolio items are fictional.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    result = run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
