import pytest

from agent.sample_data import portfolio_items
from rag.retriever import retrieve
from rag.verify import remove_unsupported_claims, verify_claims


def test_retrieval_variants_return_evidence():
    items = [item for item in portfolio_items() if item["evidence_id"] == "evidence-001"]
    for variant in ("V0", "V1", "V2", "V3", "V4", "V8"):
        result = retrieve(variant, "Python classification model evaluation", items)
        assert result
        assert result[0][0]["evidence_id"] == "evidence-001"


def test_claim_verifier_and_filter():
    evidence = portfolio_items()
    draft = "My portfolio includes Customer churn classification coursework. I guarantee you a 100% success rate."
    checks = verify_claims(draft, evidence)
    assert checks[0]["status"] == "supported"
    assert checks[1]["status"] != "supported"
    filtered, kept = remove_unsupported_claims(draft, checks)
    assert "guarantee" not in filtered.lower()
    assert len(kept) == 1


def test_invalid_retrieval_input_is_rejected():
    with pytest.raises(ValueError):
        retrieve("V0", "  ", portfolio_items())
    with pytest.raises(ValueError):
        retrieve("unknown", "Python", portfolio_items())
