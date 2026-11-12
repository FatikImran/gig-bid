from __future__ import annotations

from agent.handoffs import JobSpec, ProposalDraft


def draft(job: JobSpec, evidence: list[dict]) -> ProposalDraft:
    if not evidence:
        return ProposalDraft(
            job_id=job.job_id,
            cover_letter="I do not have verified portfolio evidence to support a proposal for this job.",
        )
    item = evidence[0]
    return ProposalDraft(
        job_id=job.job_id,
        cover_letter=f"My portfolio includes {item['title']}. {item['summary']}",
        evidence_ids=[str(item["evidence_id"])],
    )
