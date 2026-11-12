from __future__ import annotations

import pytest

from agent.sample_data import jobs
from evals.runners import evaluate_gigsim
from evals.runners.prepare_kaggle_data import _scenario_job


@pytest.mark.parametrize("prepared_scenario_count", [5, 40])
def test_missing_raw_csv_caps_prepared_safety_scenarios(
    monkeypatch, tmp_path, prepared_scenario_count
):
    base = jobs()[0]
    prepared_scenarios = [
        _scenario_job(base, "unpaid_off_platform", index)
        for index in range(prepared_scenario_count)
    ]
    monkeypatch.setattr(evaluate_gigsim, "RAW_JOBS", tmp_path / "missing.csv")
    monkeypatch.setattr(evaluate_gigsim, "OUTPUT", tmp_path / "evaluation.json")
    monkeypatch.setattr(
        evaluate_gigsim,
        "load_seed",
        lambda: {"jobs": [base, *prepared_scenarios], "clients": {}},
    )
    monkeypatch.setattr(
        evaluate_gigsim, "analyze_job", lambda _job: {"decision": {"action": "skip"}}
    )

    result = evaluate_gigsim.run()

    assert result["synthetic_safety_scenarios_evaluated"] == 40
    assert result["synthetic_scenario_skip_detection"]["missed_skip_count"] == 0
