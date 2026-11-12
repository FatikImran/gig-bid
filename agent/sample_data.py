from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "data" / "sample"
if not SAMPLE_DIR.is_dir():
    SAMPLE_DIR = Path(sys.prefix) / "share" / "gigbid" / "sample"


def load_json(name: str) -> list[dict[str, Any]]:
    path = SAMPLE_DIR / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load required sample data: {path.name}") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{path.name} must contain a JSON array of objects")
    return value


def jobs() -> list[dict[str, Any]]:
    sample_jobs = load_json("jobs.json")
    for index, job in enumerate(sample_jobs):
        job.setdefault("client_id", f"synthetic-client-sample-{index + 1:03d}")
        job.setdefault("data_provenance", "starter_kit_synthetic")

    seed_path = ROOT / "data" / "processed" / "gigsim_seed.json"
    use_kaggle_feed = os.getenv("GIGBID_USE_KAGGLE_FEED", "false").casefold() in {
        "1",
        "true",
        "yes",
    }
    if not use_kaggle_feed or not seed_path.is_file():
        return sample_jobs
    try:
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load prepared marketplace seed: {seed_path.name}") from exc
    imported = seed.get("jobs") if isinstance(seed, dict) else None
    if not isinstance(imported, list) or not all(isinstance(item, dict) for item in imported):
        raise ValueError("Prepared marketplace seed must contain a jobs array")
    known_ids = {item["job_id"] for item in sample_jobs}
    for item in imported:
        item.setdefault("client_id", "synthetic-client-" + hashlib.sha256(
            str(item.get("job_id", "")).encode()
        ).hexdigest()[:16])
    return sample_jobs + [item for item in imported if item.get("job_id") not in known_ids]


def freelancers() -> list[dict[str, Any]]:
    return load_json("freelancers.json")


def portfolio_items() -> list[dict[str, Any]]:
    return load_json("portfolio_items.json")


def client_history() -> list[dict[str, Any]]:
    return load_json("client_history.json")
