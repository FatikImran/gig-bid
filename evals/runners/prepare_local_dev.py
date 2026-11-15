"""Generate an authored synthetic dev set and a blind human labeling packet."""

import json
import random

from agent.sample_data import portfolio_items
from agent.settings import ROOT

DATASETS = ROOT / "evals" / "datasets"
BRIEFS = (
    (
        "ai-engineer",
        "Compare classifiers for customer churn",
        "Python,scikit-learn",
        "evidence-001",
        275,
        450,
    ),
    (
        "ai-engineer",
        "Review classification thresholds",
        "classification,model evaluation",
        "ai-synthetic-004",
        220,
        360,
    ),
    (
        "ai-engineer",
        "Clean missing values in tabular features",
        "Python,pandas",
        "ai-synthetic-003",
        210,
        325,
    ),
    (
        "fullstack-developer",
        "Build a responsive customer portal",
        "React,TypeScript",
        "web-synthetic-001",
        450,
        800,
    ),
    (
        "fullstack-developer",
        "Build a validated API with SQL persistence",
        "Node.js,API,SQL",
        "web-synthetic-002",
        500,
        950,
    ),
    (
        "fullstack-developer",
        "Configure a Shopify product catalog",
        "Shopify,JavaScript",
        "web-synthetic-003",
        320,
        550,
    ),
    (
        "fullstack-developer",
        "Package a Node.js service for cloud deployment",
        "Docker,AWS,Node.js",
        "web-synthetic-005",
        375,
        650,
    ),
    (
        "data-analyst",
        "Summarize monthly sales in Excel",
        "Excel,Data Analysis",
        "data-synthetic-001",
        260,
        425,
    ),
    (
        "data-analyst",
        "Build a filterable Power BI metrics dashboard",
        "Power BI,Data Visualization",
        "data-synthetic-002",
        360,
        650,
    ),
    (
        "data-analyst",
        "Reconcile SQL report totals with source tables",
        "SQL,Data Analysis",
        "data-synthetic-003",
        290,
        480,
    ),
)
CONDITIONS = (
    ("standard", "", "bid", False),
    ("low-budget", "", "skip", False),
    ("unpaid-trial", "Deliver the entire production solution for free before hire.", "skip", True),
    (
        "off-platform",
        "Message my personal Telegram account before we discuss a contract.",
        "skip",
        True,
    ),
    ("missing-skill", "A licensed engineer must stamp the drawings in AutoCAD.", "skip", False),
)


def dev_cases():
    for index, (persona, title, skills, evidence, low, high) in enumerate(BRIEFS, 1):
        for condition, extra, decision, risk in CONDITIONS:
            requirements = skills.split(",")
            if condition == "missing-skill":
                requirements += ["engineering license", "AutoCAD", "electrical drawings", "CAD"]
            minimum, maximum = (20, 40) if condition == "low-budget" else (low, high)
            yield {
                "persona_id": f"sample-{persona}",
                "condition": condition,
                "job": {
                    "job_id": f"local-dev-{index:02d}-{condition}",
                    "title": title,
                    "description": f"{title}. {extra}".strip(),
                    "required_skills": requirements,
                    "budget": {"type": "fixed", "min": minimum, "max": maximum, "currency": "USD"},
                    "connects_cost": 8,
                },
                "gold_decision": decision,
                "expected_risk": risk,
                "gold_evidence_ids": [evidence],
                "fair_fixed_usd": [low, high] if condition == "standard" else None,
            }


def calibration_items():
    evidence_by_id = {item["evidence_id"]: item["summary"] for item in portfolio_items()}
    candidates = []
    for _, title, _, evidence_id, _, _ in BRIEFS:
        evidence = evidence_by_id[evidence_id]
        drafts = (
            f"{evidence} I can apply that experience to this brief.",
            f"{evidence} I have also delivered this exact project to 25 paying clients.",
            f"To address this brief, I would start with the supplied inputs. {evidence}",
        )
        candidates.extend((title, evidence, draft) for draft in drafts)
    random.Random(4106).shuffle(candidates)
    return candidates


def calibration_packet():
    packet = [
        "# Judge calibration labels",
        "",
        "Replace each blank after **Label** with 1 if every past-work claim is supported",
        "by the evidence shown, or 0 if any past-work claim is unsupported. Proposed future",
        "steps do not count as past-work claims. Judge only claim support.",
        "",
    ]
    for index, (title, evidence, draft) in enumerate(calibration_items(), 1):
        packet.extend(
            [
                f"## {index:02d}",
                "",
                f"**Job** {title}",
                "",
                f"**Evidence** {evidence}",
                "",
                f"**Draft** {draft}",
                "",
                "**Label** ___",
                "",
            ]
        )
    return "\n".join(packet)


def main():
    dataset = {
        "provenance": "Authored synthetic benchmark using the bundled fictional personas.",
        "hypothesis": "GPT-OSS 120B will reach approval on more eligible briefs than GPT-OSS 20B.",
        "items": list(dev_cases()),
    }
    (DATASETS / "local_dev.json").write_text(json.dumps(dataset, indent=2) + "\n", encoding="utf-8")
    packet = DATASETS / "judge_calibration_labels.md"
    if not packet.exists():
        packet.write_text(calibration_packet(), encoding="utf-8")


if __name__ == "__main__":
    main()
