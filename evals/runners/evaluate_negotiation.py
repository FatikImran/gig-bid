from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.graphs.negotiation_graph import build_negotiation_graph
from agent.sample_data import freelancers

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "evals" / "results" / "negotiation_eval.json"
OFFER_RATIOS = (0.6, 0.9, 1.0, 1.2)
CASE_COUNT = 40


def _client_ceiling(index: int, floor: float, offered: float, walk_away: bool) -> float:
    if walk_away:
        return floor * 0.8
    if offered < floor:
        return floor * (0.8 + 0.15 * (index % 3))
    return max(offered, floor * 1.1)


def run() -> dict[str, Any]:
    graph = build_negotiation_graph()
    personas = freelancers()
    decisions = []
    simulation_results = []

    for index in range(CASE_COUNT):
        profile = personas[index % len(personas)]
        unit = "hourly" if index % 2 == 0 else "fixed"
        floor = float(
            profile["hourly_rate_usd"]
            if unit == "hourly"
            else profile["minimum_project_budget_usd"]
        )
        walk_away_case = index % 8 == 7
        ceiling = floor * (0.8 if walk_away_case else 1.5)
        ratio = OFFER_RATIOS[(index // 2) % len(OFFER_RATIOS)]
        offered = round(floor * ratio, 2)
        message = (
            f"The client offers ${offered:.2f}/hour."
            if unit == "hourly"
            else f"The client offers ${offered:.2f} for the project."
        )
        result = graph.invoke(
            {
                "message": message,
                "job": {
                    "job_id": f"synthetic-negotiation-{index + 1:02d}",
                    "budget": {"type": unit, "min": 0, "max": ceiling},
                },
                "profile": profile,
            }
        )["decision"]
        expected_walk_away = floor > ceiling
        predicted_walk_away = result["action"] == "walk_away"
        decisions.append(
            {
                "id": f"NG-{index + 1:02d}",
                "action": result["action"],
                "expected_walk_away": expected_walk_away,
                "predicted_walk_away": predicted_walk_away,
                "offer": offered,
                "recommended": result["recommended_amount"],
                "floor": floor,
                "ceiling": ceiling,
                "unit": unit,
            }
        )

        if result["action"] not in {"accept", "counter"}:
            simulation_results.append({"accepted": False, "achieved": None, "offered": offered})
            continue
        buyer_ceiling = _client_ceiling(
            index, floor, offered, expected_walk_away
        )
        proposed = float(result["recommended_amount"])
        accepted = proposed <= buyer_ceiling
        simulation_results.append(
            {
                "accepted": accepted,
                "achieved": proposed if accepted else None,
                "offered": offered,
            }
        )

    true_walkaways = sum(
        case["expected_walk_away"] and case["predicted_walk_away"] for case in decisions
    )
    predicted_walkaways = sum(case["predicted_walk_away"] for case in decisions)
    expected_walkaways = sum(case["expected_walk_away"] for case in decisions)
    eligible = [case for case in simulation_results if case["achieved"] is not None]
    acceptance_count = len(eligible)
    rate_change = (
        sum(
            (case["achieved"] - case["offered"]) / case["offered"]
            for case in eligible
            if case["offered"] > 0
        )
        / acceptance_count
        if acceptance_count
        else None
    )
    result = {
        "evaluation": "GigBid synthetic negotiation subgraph evaluation",
        "dataset_type": "authored_synthetic_negotiation_cases",
        "case_count": len(decisions),
        "persona_count": len(personas),
        "walkaway": {
            "expected_count": expected_walkaways,
            "predicted_count": predicted_walkaways,
            "precision": true_walkaways / predicted_walkaways if predicted_walkaways else None,
            "recall": true_walkaways / expected_walkaways if expected_walkaways else None,
        },
        "below_floor_counter_count": sum(
            case["action"] == "counter" and case["recommended"] < case["floor"]
            for case in decisions
        ),
        "synthetic_client_simulation": {
            "actionable_case_count": sum(
                item["action"] in {"accept", "counter"} for item in decisions
            ),
            "accepted_counter_or_offer_count": acceptance_count,
            "acceptance_rate": (
                acceptance_count
                / sum(item["action"] in {"accept", "counter"} for item in decisions)
                if any(item["action"] in {"accept", "counter"} for item in decisions)
                else None
            ),
            "mean_achieved_rate_change_vs_initial_offer": rate_change,
            "provenance": "Deterministic synthetic buyer ceilings; not client behavior.",
        },
        "cases": decisions,
        "limitations": [
            "All offers and buyer ceilings are authored synthetic data.",
            "The local buyer response rule is deterministic and is not the instructor's GigSim.",
            "No real client acceptance, negotiation history, or market-rate outcome is measured.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    result = run()
    print(json.dumps(result, indent=2))
    if result["below_floor_counter_count"] != 0:
        raise SystemExit("Negotiation safety gate failed: below-floor counteroffer found.")


if __name__ == "__main__":
    main()
