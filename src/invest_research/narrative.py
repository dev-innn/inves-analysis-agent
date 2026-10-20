"""Shared numeric policy for agent drafts and final report validation."""
from __future__ import annotations

import re
from collections.abc import Iterable

from .schemas import DraftResult, Metric, Source
from .numeric_claims import numeric_checks


NARRATIVE_RULE = (
    "正文允许引用已核验指标数值；每个数值必须紧跟单位和唯一指标引用，"
    "格式：2025年营收同比为6.43%（metric_id: 营收同比-2025）。示例仅说明格式，必须采用实际指标。"
    "金额明确写美元/万美元/百万美元/亿美元/十亿美元，百分比用%，比率用倍。"
    "接近或约为只允许百分之一以内误差，并满足所写精度的舍入；例如比率0.995可表述接近1。"
    "期间必须与指标一致；不要混用季度与年度、百分比与百分点。不要自行推算新的数值或因果。"
    "保留已知source_ids、metric_ids、财报原文中的产品型号及SEC表单名称10-K、10-Q、8-K（含/A）。"
    "未提供已核验指标的数字、日期和年份改用定性文字，不要用中文数字规避。"
)


def narrative_references(research: dict, analysis: dict, sources: Iterable[Source | dict] = (), documents: Iterable[dict] = ()) -> list[str]:
    # XBRL sources can be added after research. Use the complete source catalog
    # for both guardrails, rather than only research's selected source IDs.
    references = [*research.get("source_ids", []), *analysis.get("metric_ids", [])]
    references.extend(Source.model_validate(source).source_id for source in sources)
    # A model code is a lexical exemption, not proof of the surrounding claim.
    # Require an exact occurrence in both prior research and a downloaded filing;
    # never exempt arbitrary alphanumeric text produced by the writer.
    code = re.compile(r"(?<![A-Za-z0-9_./-])[A-Z]{1,5}\d{2,4}[A-Z]?(?![A-Za-z0-9_/-]|\.\d)")
    claims = "\n".join([research.get("company_summary", ""), *research.get("developments", []), *research.get("risks", [])])
    original_codes = {m.group() for doc in documents for m in code.finditer(doc.get("text", ""))}
    for match in code.finditer(claims):
        token = match.group()
        if token in original_codes and not re.match(r"(?:FY|CY|USD|CNY|EUR|HKD|JPY)\d", token):
            references.append(token)
    return list(dict.fromkeys(references))


def _allowed_pattern(references: Iterable[str]) -> re.Pattern:
    # Mask exact trusted identifiers only. Keep offsets so diagnostics point to
    # the original text; do not change the generated report or its citations.
    tokens = sorted({token for token in references if token and not token.isdecimal()}, key=len, reverse=True)
    alternatives = [re.escape(token) for token in tokens]
    alternatives.append(r"(?:10-[KQ]|8-K)(?:/A)?")
    return re.compile(r"(?<![A-Za-z0-9_./$€£¥-])(?:" + "|".join(alternatives) + r")(?![A-Za-z0-9_/-]|\.\d|[%％]|美元|万美元|百万美元|亿美元|十亿美元|倍|个百分点)")
def narrative_number_issues(draft: DraftResult, references: Iterable[str] = (), metrics: Iterable[Metric | dict] = ()) -> list[dict]:
    verified = [Metric.model_validate(m) for m in metrics]
    references = [*references, *(m.metric_id for m in verified)]
    allowed = _allowed_pattern(references)
    issues = []
    for field, text in draft.model_dump().items():
        masked = allowed.sub(lambda match: " " * len(match.group()), text)
        for check in numeric_checks(text, masked, verified):
            if check["reason"]:
                issues.append({"field": field, "number": text[check["start"]:check["end"]], "start": check["start"], "end": check["end"], "reason": check["reason"], "excerpt": text[max(0, check["start"] - 24):check["end"] + 60]})
    return issues


def narrative_error(issues: list[dict]) -> str:
    details = "；".join(f"{item['field']}：{item['excerpt']!r}（{item.get('reason', '数字无法核验')}）" for item in issues)
    return f"叙述包含无法核验的数字：{details}。请只改写这些数字所在的表述；保留已知来源/指标 ID 和 SEC 表单名称。"


def withdraw_numeric_sentences(draft: DraftResult, references: Iterable[str] = (), metrics: Iterable[Metric | dict] = ()) -> tuple[DraftResult, list[dict]]:
    """Conservative fallback: withdraw whole assertions, never invent a paraphrase.

    Split only outside trusted identifiers. Decimal points are not sentence
    boundaries. Keep the associated explanation in the withdrawn sentence so
    unsupported causal conclusions do not survive as orphaned clauses.
    """
    references = list(references)
    metrics = list(metrics)
    references.extend(Metric.model_validate(m).metric_id for m in metrics)
    issues = narrative_number_issues(draft, references, metrics)
    allowed = _allowed_pattern(references)
    values = draft.model_dump()
    changes = []
    for field, text in values.items():
        masked = allowed.sub(lambda m: " " * len(m.group()), text)
        boundaries = [m.end() for m in re.finditer(r"[。！？!?\n]|\.(?=\s|$)", masked)]
        start, parts = 0, []
        for end in [*boundaries, len(text)]:
            if end <= start:
                continue
            sentence = text[start:end]
            if any(i["field"] == field and start <= i["start"] < end for i in issues):
                citations = list(dict.fromkeys(m.group() for m in allowed.finditer(sentence)))
                replacement = "相关定量表述已撤回，请参见指标表及原始来源"
                if citations:
                    replacement += "（" + "、".join(citations) + "）"
                replacement += "。"
                parts.append(replacement)
                changes.append({"field": field, "original": sentence, "replacement": replacement})
            else:
                parts.append(sentence)
            start = end
        values[field] = "".join(parts)
    if changes:
        values["gaps"] += "\n部分定量叙述在自动改写后仍未通过数字规则校验，已撤回对应整句及其解释；数值请查阅财务指标表，撤回记录保存在撰写校验产出中。"
    repaired = DraftResult.model_validate(values)
    if narrative_number_issues(repaired, references, metrics):
        raise ValueError("撤回定量叙述后仍包含未允许的数字")
    return repaired, changes
