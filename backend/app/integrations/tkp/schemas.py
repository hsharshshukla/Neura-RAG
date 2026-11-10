from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProjectionType(StrEnum):
    QA = "QA"
    PROCEDURE = "PROCEDURE"
    TROUBLESHOOTING = "TROUBLESHOOTING"
    SUMMARY = "SUMMARY"


class KnowledgeScope(StrEnum):
    GENERAL = "GENERAL"
    PRODUCT_SPECIFIC = "PRODUCT_SPECIFIC"
    VERSION_SPECIFIC = "VERSION_SPECIFIC"
    CASE_SPECIFIC = "CASE_SPECIFIC"
    INTERNAL = "INTERNAL"


class ResolutionStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    UNCONFIRMED = "UNCONFIRMED"
    MIXED = "MIXED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RetrievalStrategy(StrEnum):
    LEXICAL = "LEXICAL"
    VECTOR = "VECTOR"
    HIERARCHICAL = "HIERARCHICAL"
    GRAPH_ASSISTED = "GRAPH_ASSISTED"
    MULTI_STRATEGY = "MULTI_STRATEGY"


class BrowserRetrievalRequest(BaseModel):
    """Safe browser contract; workspace and backend controls are intentionally absent."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=1000)
    product_names: tuple[str, ...] = Field(default=(), max_length=32)
    product_versions: tuple[str, ...] = Field(default=(), max_length=32)
    technical_entity_names: tuple[str, ...] = Field(default=(), max_length=32)
    technical_entity_versions: tuple[str, ...] = Field(default=(), max_length=32)
    projection_types: tuple[ProjectionType, ...] = Field(default=(), max_length=4)
    knowledge_scope: tuple[KnowledgeScope, ...] = Field(default=(), max_length=5)
    resolution_status: tuple[ResolutionStatus, ...] = Field(default=(), max_length=4)
    limit: int = Field(default=10, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=90)

    @model_validator(mode="after")
    def unique_filters(self) -> BrowserRetrievalRequest:
        values = (
            self.product_names,
            self.product_versions,
            self.technical_entity_names,
            self.technical_entity_versions,
            self.projection_types,
            self.knowledge_scope,
            self.resolution_status,
        )
        if any(len(items) != len(set(items)) for items in values):
            raise ValueError("Retrieval filters must not contain duplicates")
        if self.offset + self.limit > 100:
            raise ValueError("offset plus limit must not exceed the backend candidate budget")
        return self


class TKPRetrievalRequest(BrowserRetrievalRequest):
    """Server-to-server TKP request with security-sensitive choices fixed by Neura."""

    backend_limit: int = Field(default=50, ge=1, le=100)
    ancestor_limit: int = Field(default=4, ge=0, le=8)
    descendant_limit: int = Field(default=16, ge=0, le=64)
    related_limit: int = Field(default=4, ge=0, le=32)
    context_item_limit: int = Field(default=24, ge=0, le=100)
    context_character_limit: int = Field(default=20_000, ge=256, le=100_000)
    graph_max_hops: int = 2
    graph_node_limit: int = 50
    graph_edge_limit: int = 100
    graph_path_limit: int = 50
    diagnostic: bool = False
    experimental_opensearch: bool = False
    retrieval_configuration: str = "ROUTED"
    vector_search_mode: str = "EXACT"
    vector_minimum_similarity: float = 0.0

    @classmethod
    def from_browser(cls, request: BrowserRetrievalRequest) -> TKPRetrievalRequest:
        backend_limit = max(50, request.offset + request.limit)
        return cls(**request.model_dump(), backend_limit=backend_limit)


class SearchMatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str
    value: str | None = None


class ClaimReference(BaseModel):
    model_config = ConfigDict(extra="ignore")
    revision_claim_id: UUID
    candidate_claim_id: UUID
    source_fragment_ids: tuple[UUID, ...]


class SourceFragmentReference(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source_fragment_id: UUID
    source_id: UUID
    source_version_id: UUID
    source_revision_number: int | None = None
    locator_kind: str
    locator: dict[str, Any]


class PageRange(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source_id: UUID
    source_version_id: UUID
    page_start: int
    page_end: int


class HierarchyNode(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    parent_id: UUID | None
    node_type: str
    depth: int
    order: int
    heading: str
    heading_path: tuple[str, ...]
    content: str | None = None
    projection_id: UUID | None = None
    article_id: UUID
    revision_id: UUID
    revision_number: int
    claim_references: tuple[ClaimReference, ...] = ()
    source_references: tuple[SourceFragmentReference, ...] = ()
    page_ranges: tuple[PageRange, ...] = ()


class HierarchyContextItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    relation: str
    node: HierarchyNode


class HierarchyResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    score: float
    matches: tuple[SearchMatch, ...]
    matched_section: HierarchyNode | None
    matched_block: HierarchyNode
    context: tuple[HierarchyContextItem, ...]
    context_characters: int


class StrategyContribution(BaseModel):
    model_config = ConfigDict(extra="ignore")
    strategy: RetrievalStrategy
    rank: int
    reciprocal_rank_score: float
    backend_score: float | None = None


class RankingDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rrf_k: int
    rrf_score: float
    exact_identifier_bonus: float
    final_score: float
    contributions: tuple[StrategyContribution, ...]


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rank: int
    projection_id: UUID
    projection_type: ProjectionType
    title: str
    question: str | None
    content: str
    retrieval_text: str
    matches: tuple[SearchMatch, ...]
    product_names: tuple[str, ...]
    product_versions: tuple[str, ...]
    related_technologies: tuple[str, ...]
    exact_terms: tuple[str, ...]
    knowledge_scope: KnowledgeScope
    resolution_status: ResolutionStatus
    article_id: UUID
    revision_id: UUID
    claim_references: tuple[ClaimReference, ...]
    hierarchy: HierarchyResult | None = None
    graph: dict[str, Any] | None = None
    ranking: RankingDetails


class BackendStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    strategy: RetrievalStrategy
    backend: str
    attempted: bool
    available: bool
    degraded: bool = False
    fallback_backend: str | None = None
    reason: str | None = None
    deadline_seconds: float
    timed_out: bool = False
    result_count: int = 0
    calls: int = 0
    latency_ms: float = 0


class TKPRetrievalResponse(BaseModel):
    """Required TKP response fields; additive upstream fields remain compatible."""

    model_config = ConfigDict(extra="ignore")
    analysis: dict[str, Any]
    plan: dict[str, Any]
    results: tuple[RetrievalResult, ...]
    backend_status: tuple[BackendStatus, ...]
    total: int
    limit: int
    offset: int
    has_more: bool
    backend_calls: int
    correlation_id: UUID


class TKPErrorBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str
    message: str
    correlation_id: UUID
    details: dict[str, Any] | None = None
