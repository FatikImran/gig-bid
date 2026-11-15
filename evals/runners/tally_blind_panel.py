"""Validate and tally completed blind proposal review replies."""

import json
import re
from collections import Counter

from agent.settings import ROOT

RESULTS = ROOT / "evals" / "results"
KEY = ROOT / "data" / "processed" / "blind_proposal_panel_key.json"
RATING = re.compile(r"^(P\d+)\s*\|\s*choice:\s*(A|B|Tie)\s*\|\s*reason:\s*(\S.*)$")


def main():
    key = json.loads(KEY.read_text(encoding="utf-8"))
    replies = sorted(RESULTS.glob("blind_proposal_panel_reviewer_*.md"))
    if not replies:
        raise SystemExit("No reviewer replies found.")
    reviewers = set()
    by_pair = {case: Counter() for case in key}
    for path in replies:
        text = path.read_text(encoding="utf-8")
        codes = re.findall(r"(?m)^Reviewer code:\s*(\S[^\n]*)$", text)
        if len(codes) != 1:
            raise SystemExit(f"{path.name} must have one reviewer code.")
        code = codes[0].strip().casefold()
        if code in reviewers:
            raise SystemExit(f"{path.name} duplicates a reviewer code.")
        reviewers.add(code)
        ratings = {}
        for line in text.splitlines():
            match = RATING.fullmatch(line.strip())
            if match:
                case, choice, reason = match.groups()
                if case in ratings or reason.strip() == "___":
                    raise SystemExit(f"{path.name} has an invalid rating for {case}.")
                ratings[case] = choice
        if ratings.keys() != key.keys():
            raise SystemExit(f"{path.name} does not rate every pair exactly once.")
        for case, choice in ratings.items():
            by_pair[case][key[case][choice] if choice != "Tie" else "tie"] += 1
    totals = sum(by_pair.values(), Counter())
    result = {
        "reviewers": len(reviewers),
        "pairs": len(key),
        "ratings": totals.total(),
        "totals": totals,
        "by_pair": by_pair,
    }
    (RESULTS / "blind_proposal_panel_summary.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
