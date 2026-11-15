from __future__ import annotations

from agent.handoffs import JobSpec, ProposalDraft
from agent.model_runtime import enabled, generate


def draft(job: JobSpec, evidence: list[dict]) -> ProposalDraft:
    if not evidence:
        return ProposalDraft(
            job_id=job.job_id,
            cover_letter="I do not have verified portfolio evidence to support a proposal for this job.",
        )
    item = evidence[0]
    if enabled():
        result = generate(
            "writer",
            {"job": job.model_dump(), "evidence": evidence},
            {
                "type": "object",
                "properties": {"cover_letter": {"type": "string"}},
                "required": ["cover_letter"],
                "additionalProperties": False,
            },
        )
        return ProposalDraft(
            job_id=job.job_id,
            cover_letter=result["cover_letter"],
            evidence_ids=[str(item["evidence_id"]) for item in evidence],
        )
    return ProposalDraft(
        job_id=job.job_id,
        cover_letter=f"My portfolio includes {item['title']}. {item['summary']}",
        evidence_ids=[str(item["evidence_id"])],
    )
