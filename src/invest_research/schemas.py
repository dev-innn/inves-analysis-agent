from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    ticker: str | None = Field(default=None, max_length=12)
    as_of_date: date = Field(default_factory=date.today)
    report_periods: int = Field(default=3, ge=1, le=5)
    report_language: Literal["zh"] = "zh"


class Candidate(BaseModel):
    cik: int
    ticker: str
    legal_name: str


class Source(BaseModel):
    source_id: str
    type: str
    title: str
    url: HttpUrl
    publisher: str
    fetched_at: str = Field(default_factory=utcnow)
    published_at: str | None = None
    accession: str | None = None
    content_hash: str | None = None
    pdf_page: int | None = None


class Fact(BaseModel):
    fact_id: str
    name: str
    value: float
    unit: str
    start: str | None = None
    end: str
    fy: int | None = None
    fp: str | None = None
    form: str
    filed_at: str
    accession: str
    source_id: str
    taxonomy: str
    concept: str


class Metric(BaseModel):
    metric_id: str
    name: str
    value: float | None
    unit: str
    period: str
    formula: str
    operand_fact_ids: list[str]
    source_ids: list[str]
    status: Literal["verified", "unavailable", "needs_review"]
    reason: str | None = None


class ClaimEvidence(BaseModel):
    claim: str = Field(description="逐字复制 company_summary、developments 或 risks 中的一整项结论")
    source_id: str
    quote: str = Field(min_length=20, description="支持结论的连续原文，包含期间、主体和方向，禁止改写")
    verdict: Literal["supported", "unsupported", "contradicted"]
    explanation: str = Field(description="中文说明原文如何支持或反驳结论")


class ResearchResult(BaseModel):
    evidence: list[ClaimEvidence] = Field(default_factory=list)
    company_summary: str
    developments: list[str]
    risks: list[str]
    source_ids: list[str]
    gaps: list[str] = Field(default_factory=list, description="影响核心结论的证据缺口；必须补齐或撤回相关结论")
    limitations: list[str] = Field(default_factory=list, description="不影响已验证结论的范围限制；不得包含核心证据缺失")


class AnalysisResult(BaseModel):
    profitability: str
    cash_flow: str
    trends: list[str]
    risks: list[str]
    metric_ids: list[str]
    gaps: list[str] = Field(default_factory=list, description="影响核心结论的证据缺口；必须补齐或撤回相关结论")
    limitations: list[str] = Field(default_factory=list, description="不影响已验证结论的范围限制；不得包含核心证据缺失")


class DraftResult(BaseModel):
    summary: str
    business: str
    developments: str
    financial_analysis: str
    risks: str
    gaps: str


STAGES = ["identity", "research", "analysis", "writing", "validation"]
TERMINAL = {"succeeded", "needs_review", "failed"}


class Supplement(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    url: HttpUrl
    published_at: date
    content: str = Field(min_length=20, max_length=30000)


class ReanalysisRequest(BaseModel):
    mode: Literal["complete_evidence", "remove_unsupported"] = "complete_evidence"
    supplements: list[Supplement] = Field(default_factory=list, max_length=5)
