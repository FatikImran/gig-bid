"""Compare blinded human labels with Groq judge labels and report Cohen's kappa."""

import json
import os
import re

from agent.model_runtime import generate
from agent.settings import ROOT
from evals.runners.prepare_local_dev import DATASETS, calibration_packet

SCHEMA = {
    "type": "object",
    "properties": {
        "judgments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "label": {"type": "integer", "enum": [0, 1]},
                },
                "required": ["id", "label"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["judgments"],
    "additionalProperties": False,
}


def main():
    packet = (DATASETS / "judge_calibration_labels.md").read_text(encoding="utf-8")
    label_pattern = r"(?m)^\*\*Label\*\* +([01]) *$"
    human = [int(label) for label in re.findall(label_pattern, packet)]
    if len(human) != 30:
        raise SystemExit(
            f"Complete all 30 human labels before running the judge ({len(human)} found)."
        )
    blinded = re.sub(label_pattern, "**Label** ___", packet)
    if blinded.rstrip() != calibration_packet().rstrip():
        raise SystemExit("Only edit the Label fields so case IDs and text remain reproducible.")
    items = []
    for case in blinded.split("\n## ")[1:]:
        case_id, text = case.strip().split("\n", 1)
        items.append({"id": int(case_id), "case": text.replace("**Label** ___", "").strip()})
    os.environ["GIGBID_MODEL_PROVIDER"] = "groq"
    os.environ["GROQ_MODEL"] = "openai/gpt-oss-120b"
    judged = {}
    for start in range(0, len(items), 5):
        batch = items[start : start + 5]
        response = generate("judge_calibration", {"items": batch}, SCHEMA)["judgments"]
        if sorted(row["id"] for row in response) != sorted(item["id"] for item in batch):
            raise RuntimeError("Judge response omitted, duplicated or changed a case ID.")
        judged.update((row["id"], row["label"]) for row in response)
    model = [judged[index] for index in range(1, len(human) + 1)]
    agreement = sum(a == b for a, b in zip(human, model)) / len(human)
    human_positive, model_positive = sum(human) / len(human), sum(model) / len(model)
    chance = human_positive * model_positive + (1 - human_positive) * (1 - model_positive)
    result = {
        "model": os.environ["GROQ_MODEL"],
        "criterion": "All past-work claims are supported by supplied evidence.",
        "cases": len(human),
        "agreement": agreement,
        "cohens_kappa": (agreement - chance) / (1 - chance) if chance < 1 else None,
        "labels": [
            {"id": index, "human": a, "judge": b}
            for index, (a, b) in enumerate(zip(human, model), 1)
        ],
    }
    output = ROOT / "evals" / "results" / "judge_calibration.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "labels"}, indent=2))


if __name__ == "__main__":
    main()
