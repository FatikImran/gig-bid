"""Two-stage lexical retrieval with a transparent overlap reranker."""

from rag.variants.v0_naive import retrieve as first_stage


def retrieve(query: str, index: list[dict], k: int = 5):
    candidates = first_stage(query, index, k=max(k, min(len(index), 20)))
    query_terms = {word.lower() for word in query.split() if len(word) > 2}

    def rerank(row):
        item, initial = row
        text = " ".join(
            str(item.get(field, "")) for field in ("title", "summary", "skills", "outcome")
        ).lower()
        overlap = len(query_terms & set(text.split())) / max(1, len(query_terms))
        return item, initial * 0.5 + overlap * 0.5

    return sorted((rerank(row) for row in candidates), key=lambda row: row[1], reverse=True)[:k]
