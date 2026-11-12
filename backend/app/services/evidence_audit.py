from __future__ import annotations

from app.integrations.tkp.schemas import TKPRetrievalRequest, TKPRetrievalResponse
from app.models import AnswerEvidenceAudit
from app.services.grounded_answer import GroundedAnswer


def build_answer_evidence_audit(
    *,
    session_id: int,
    user_id: int,
    workspace_id: str,
    user_message_id: int,
    assistant_message_id: int,
    original_query: str,
    standalone_query: str,
    history_message_ids: tuple[int, ...],
    retrieval_request: TKPRetrievalRequest | None,
    retrieval: TKPRetrievalResponse | None,
    answer: GroundedAnswer,
    answer_model: str,
    prompt_policy_version: str,
    validation_status: str,
    client_request_id: str | None = None,
) -> AnswerEvidenceAudit:
    lineage = []
    backend_status = []
    correlation_id = None
    if retrieval is not None:
        correlation_id = str(retrieval.correlation_id)
        backend_status = [item.model_dump(mode="json") for item in retrieval.backend_status]
        lineage = [
            {
                "projection_id": str(result.projection_id),
                "article_id": str(result.article_id),
                "revision_id": str(result.revision_id),
                "resolution_status": result.resolution_status.value,
                "revision_claim_ids": [
                    str(claim.revision_claim_id) for claim in result.claim_references
                ],
                "candidate_claim_ids": [
                    str(claim.candidate_claim_id) for claim in result.claim_references
                ],
                "source_fragment_ids": [
                    str(fragment_id)
                    for claim in result.claim_references
                    for fragment_id in claim.source_fragment_ids
                ],
            }
            for result in retrieval.results
        ]

    return AnswerEvidenceAudit(
        session_id=session_id,
        user_id=user_id,
        workspace_id=workspace_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        client_request_id=client_request_id,
        original_query=original_query,
        standalone_query=standalone_query,
        history_message_ids=list(history_message_ids),
        tkp_correlation_id=correlation_id,
        tkp_request=(
            retrieval_request.model_dump(mode="json") if retrieval_request is not None else {}
        ),
        evidence_lineage=lineage,
        backend_status=backend_status,
        citation_map=[citation.model_dump(mode="json") for citation in answer.citations],
        answer_model=answer_model,
        prompt_policy_version=prompt_policy_version,
        validation_status=validation_status,
        answer_confidence=answer.confidence,
        insufficient_evidence=answer.insufficient_evidence,
        insufficient_reason=answer.insufficient_reason,
    )
