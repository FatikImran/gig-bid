from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from agent.sample_data import freelancers, portfolio_items
from rag.variants.v2_hybrid import retrieve

mcp = FastMCP("GigBid Portfolio")


def search_evidence(
    requirement: str,
    k: int = 5,
    filters: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not requirement.strip():
        raise ValueError("requirement cannot be empty")
    if not 1 <= k <= 20:
        raise ValueError("k must be between 1 and 20")
    items = portfolio_items()
    if filters:
        unknown = set(filters) - {"freelancer_id", "type", "outcome"}
        if unknown:
            raise ValueError(f"Unsupported evidence filters: {', '.join(sorted(unknown))}")
        items = [
            item
            for item in items
            if all(
                str(item.get(key, "")).casefold() == value.casefold()
                for key, value in filters.items()
            )
        ]
    return [{"score": score, **item} for item, score in retrieve(requirement, items, k)]


def get_case_study(case_id: str) -> dict[str, Any]:
    if not case_id.strip():
        raise ValueError("case_id cannot be empty")
    found = next((item for item in portfolio_items() if item["evidence_id"] == case_id), None)
    if found is None:
        raise ValueError("Evidence item not found")
    return found


def list_skills(freelancer_id: str | None = None) -> list[str]:
    profiles = freelancers()
    if freelancer_id:
        profiles = [profile for profile in profiles if profile["freelancer_id"] == freelancer_id]
        if not profiles:
            raise ValueError("Freelancer profile not found")
    return sorted(
        {skill for profile in profiles for skill in profile.get("skills", [])}, key=str.casefold
    )


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
def search_portfolio_evidence(
    requirement: Annotated[str, Field(min_length=1, max_length=500)],
    k: Annotated[int, Field(ge=1, le=20)] = 5,
    filters: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Find relevant portfolio items with their source, outcome, and match score."""
    return search_evidence(requirement, k, filters)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
def get_case_study_tool(
    case_id: Annotated[str, Field(min_length=1, max_length=128)],
) -> dict[str, Any]:
    """Load a full portfolio case study by evidence ID."""
    return get_case_study(case_id)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
def list_portfolio_skills(
    freelancer_id: Annotated[str | None, Field(max_length=128)] = None,
) -> list[str]:
    """List skills explicitly present in the selected freelancer profile."""
    return list_skills(freelancer_id)


@mcp.resource("portfolio://case/{case_id}")
def portfolio_case_resource(case_id: str) -> str:
    """Read the complete portfolio case study as JSON."""
    import json

    return json.dumps(get_case_study(case_id), ensure_ascii=False)


@mcp.prompt()
def answer_screening_question(question: str, requirement: str) -> str:
    """Draft an answer to a client screening question using verifiable portfolio evidence."""
    if not question.strip() or not requirement.strip():
        raise ValueError("question and requirement are required")
    return (
        "Answer only with facts supported by retrieved portfolio items. Cite evidence IDs. "
        "If evidence is insufficient, say so instead of inventing experience.\n\n"
        f"Screening question: {question}\nRelevant requirement: {requirement}"
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
