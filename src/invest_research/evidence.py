"""Ground research claims in saved filings; never treat a source ID as proof."""
from __future__ import annotations

import re

from .schemas import ResearchResult


def normalize(text: str) -> str:
    return " ".join(text.split())


def retrieve_evidence(documents: list[dict], research: ResearchResult) -> list[dict]:
    """Search the entire saved body, including passages outside default excerpts."""
    query = " ".join([research.company_summary, *research.developments, *research.risks, *research.gaps])
    stop = {"the", "and", "for", "from", "with", "that", "this", "have", "has", "company", "information", "provided"}
    terms = set(re.findall(r"[a-z]{3,}", query.lower())) - stop
    results = []
    for doc in documents:
        # Anchor financial tables and adjacent explanations before relevance ranking.
        # Otherwise generic risk terms can crowd regional counterexamples out.
        for heading in ("products and services performance", "segment operating performance"):
            matches = list(re.finditer(re.escape(heading), doc["text"], re.I))
            for match in matches[-1:]:
                start = max(0, match.start() - 1500)
                results.append({"source_id": doc["source_id"], "offset": start, "text": doc["text"][start:match.start() + 4000]})
        passages = []
        for start in range(0, len(doc["text"]), 1400):
            passage = doc["text"][start:start + 2200]
            words = set(re.findall(r"[a-z]{3,}", passage.lower()))
            score = len(terms & words)
            passages.append((score, start, passage))
        for score, start, passage in sorted(passages, key=lambda row: (-row[0], row[1]))[:8]:
            results.append({"source_id": doc["source_id"], "offset": start, "text": passage})
    return results


def check_evidence(result: ResearchResult, documents: list[dict], *, remove: bool = False) -> list[dict]:
    """Check quotation provenance deterministically; semantic verdict is model review."""
    bodies = {d["source_id"]: normalize(d["text"]) for d in documents}
    claims = [result.company_summary, *result.developments, *result.risks]
    checks = []
    rejected = set()
    for claim in claims:
        if not claim:
            continue
        refs = [e for e in result.evidence if e.claim == claim]
        valid = bool(refs) and all(
            e.verdict == "supported" and e.source_id in result.source_ids
            and len(normalize(e.quote)) >= 20
            and normalize(e.quote) in bodies.get(e.source_id, "")
            for e in refs
        )
        reason = "；".join(e.explanation for e in refs if e.verdict != "supported")
        if not valid:
            rejected.add(claim)
            reason = reason or "缺少可在已下载财报中定位、且支持该结论的原文证据"
            for ref in refs:
                if ref.verdict == "supported":
                    ref.verdict = "unsupported"
                    ref.explanation = reason
            if not remove:
                result.gaps.append(f"结论「{claim}」：{reason}。需要补充包含主体、期间与变化方向的财报原文。")
        checks.append({"claim": claim, "passed": valid, "reason": reason, "removed": remove and not valid})
    if remove:
        result.company_summary = "" if result.company_summary in rejected else result.company_summary
        result.developments = [c for c in result.developments if c not in rejected]
        result.risks = [c for c in result.risks if c not in rejected]
        result.evidence = [e for e in result.evidence if e.claim not in rejected]
        result.limitations.extend(f"已撤回未核实结论：{claim}" for claim in dict.fromkeys(claims) if claim in rejected)
    # Missing required coverage is never waived by withdrawal.
    if not result.company_summary:
        result.gaps.append("公司业务概况缺少可核验原文，无法形成核心业务结论")
    if not result.risks:
        result.gaps.append("主要风险缺少可核验原文，无法完成核心风险分析")
    result.gaps = list(dict.fromkeys(result.gaps))
    return checks
