"""Build a source-blinded packet from matched synthetic model drafts."""

import json
import random

from agent.sample_data import portfolio_items
from agent.settings import ROOT
from evals.runners.evaluate_open_models import MODELS

DATASETS = ROOT / "evals" / "datasets"
RESULTS = ROOT / "evals" / "results"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    rows = []
    for filename in ("local_dev_groq_pilot.json", "local_dev_groq.json"):
        reports = read_json(RESULTS / filename)["runs"]
        rows.extend(row for report in reports.values() for row in report["runs"])
    extra = RESULTS / "blind_panel_additional_runs.json"
    if extra.exists():
        rows.extend(read_json(extra))
    cases = {
        item["job"]["job_id"]: item for item in read_json(DATASETS / "local_dev.json")["items"]
    }
    completed = {model: {} for model in MODELS}
    for row in rows:
        draft = row.get("draft") or {}
        if row["approval_waiting"] and draft.get("cover_letter", "").strip():
            completed[row["model"]][row["job_id"]] = draft["cover_letter"]
    eligible = sorted(set.intersection(*(set(drafts) for drafts in completed.values())))
    if not eligible:
        raise SystemExit("No matched drafts reached the approval gate.")

    portfolio = portfolio_items()
    rng = random.Random(4016)
    packet = [
        "# GigBid proposal comparison",
        "",
        "Please review independently. All jobs and portfolio evidence below are fictional.",
        "For each job, choose the proposal you would prefer to receive as the client. Consider",
        "whether it addresses the brief, supports past-work claims with the evidence, and reads",
        "clearly and professionally. Give one short reason. Choose Tie if neither has a meaningful edge.",
        "",
    ]
    key = {}
    first_models = [MODELS[index % len(MODELS)] for index in range(len(eligible))]
    rng.shuffle(first_models)
    for number, (job_id, first_model) in enumerate(zip(eligible, first_models), 1):
        case_id = f"P{number:02d}"
        item = cases[job_id]
        job = item["job"]
        order = [first_model, next(model for model in MODELS if model != first_model)]
        key[case_id] = {"job_id": job_id, **dict(zip(("A", "B"), order))}
        packet.extend(
            [
                f"## {case_id}",
                "",
                f"**Job** {job['description']}",
                "",
                f"**Required skills** {', '.join(job['required_skills'])}",
                "",
                "**Portfolio evidence**",
                "",
            ]
        )
        packet.extend(
            f"- {entry['evidence_id']}. {entry['summary']}"
            for entry in portfolio
            if entry["freelancer_id"] == item["persona_id"]
        )
        for label, model in zip(("A", "B"), order):
            packet.extend(["", f"**Proposal {label}**", "", completed[model][job_id]])
        packet.append("")

    packet.extend(
        [
            "## Reply template",
            "",
            "Copy this block into your reply and replace each blank. Use A, B, or Tie.",
            "A nickname or reviewer code is enough.",
            "",
            "```text",
            "Reviewer code: ___",
        ]
    )
    for case_id in key:
        packet.append(f"{case_id} | choice: ___ | reason: ___")
    packet.extend(["```", ""])
    (DATASETS / "blind_proposal_panel.md").write_text("\n".join(packet), encoding="utf-8")
    private_dir = ROOT / "data" / "processed"
    private_dir.mkdir(parents=True, exist_ok=True)
    (private_dir / "blind_proposal_panel_key.json").write_text(
        json.dumps(key, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Prepared {len(key)} matched proposal pairs.")


if __name__ == "__main__":
    main()
