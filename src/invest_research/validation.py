from __future__ import annotations

from datetime import date

from .schemas import DraftResult, Metric, Source
from .narrative import narrative_error, narrative_number_issues, narrative_references


def _format_value(metric: Metric) -> str:
    if metric.value is None:
        return "未披露"
    if metric.unit == "USD":
        return f"{metric.value / 1_000_000_000:,.2f} 十亿美元"
    if metric.unit == "%":
        return f"{metric.value:,.2f}%"
    return f"{metric.value:,.2f} 倍"


def render_report(company: dict, as_of: date, research: dict, analysis: dict, draft: DraftResult, metrics: list[Metric], sources: list[Source]) -> str:
    latest = max((m.period for m in metrics if m.name == "营收"), default="未知")
    research_refs = "、".join(f"[{sid}](#{sid})" for sid in research.get("source_ids", [])) or "暂无可核实来源"
    analysis_refs = "、".join(f"[{sid}](#{sid})" for sid in dict.fromkeys(sid for m in metrics if m.status == "verified" for sid in m.source_ids)) or "暂无可核实来源"
    lines = [
        f"# {company['legal_name']}（{company['ticker']}）投研初稿",
        "", f"资料截止日期：{as_of.isoformat()} · 最新完整财年：{latest} · 状态：待校验", "",
        "> 本报告由自动化系统生成，供分析师核验；推断不等同于公司披露。", "",
        "## 摘要", "", draft.summary, "",
        "## 公司与业务", "", draft.business, "", f"本节来源：{research_refs}", "",
        "## 最新披露与驱动因素", "", draft.developments, "", f"本节来源：{research_refs}", "",
        "## 三年/四季财务表", "",
        "| 指标 | 期间 | 数值 | 计算口径 | 来源 |", "| --- | --- | ---: | --- | --- |",
    ]
    for metric in metrics:
        refs = ", ".join(f"[{sid}](#{sid})" for sid in metric.source_ids) or "—"
        lines.append(f"| {metric.name} | {metric.period} | {_format_value(metric)} | {metric.formula} | {refs} |")
    lines.extend(["", "## 盈利与现金流分析", "", draft.financial_analysis, "", f"本节来源：{analysis_refs}", "", "## 主要风险", "", draft.risks, "", f"本节来源：{research_refs}", "", "## 数据缺口", "", draft.gaps])
    for label, result in (("研究资料", research), ("财报分析", analysis)):
        lines.extend(f"- 待补齐 · {label}：{gap}" for gap in result.get("gaps", []))
        lines.extend(f"- 分析局限 · {label}：{item}" for item in result.get("limitations", []))
    lines.extend(["", "## 来源目录", ""])
    for source in sources:
        lines.append(f"- [{source.title}]({source.url}) · {source.publisher} · {source.published_at or source.fetched_at}")
    return "\n".join(lines) + "\n"


def validate_report(report: str, draft: DraftResult, metrics: list[Metric], sources: list[Source], as_of: date, research: dict | None = None, analysis: dict | None = None, required_years: int = 3, *, documents: list[dict] | None = None) -> dict:
    errors = []
    sections = ["摘要", "公司与业务", "最新披露与驱动因素", "三年/四季财务表", "盈利与现金流分析", "主要风险", "数据缺口", "来源目录"]
    for section in sections:
        if f"## {section}" not in report:
            errors.append(f"缺少章节：{section}")
    if as_of.isoformat() not in report:
        errors.append("缺少资料截止日期")
    source_ids = {s.source_id for s in sources}
    for m in metrics:
        if m.status == "verified" and (not m.source_ids or not set(m.source_ids) <= source_ids or _format_value(m) not in report):
            errors.append(f"指标来源或数值无效：{m.metric_id}")
    verified_years = sorted((m.period for m in metrics if m.name == "营收" and m.status == "verified"), reverse=True)
    if len(verified_years) < required_years:
        errors.append("可核实的完整财年不足请求范围")
    quarter_periods = {m.period for m in metrics if m.name == "季度营收" and m.status == "verified"}
    if len(quarter_periods) < 4:
        errors.append("可核实的最近季度不足四个")
    annual_periods = [m.period for m in metrics if m.name == "营收"]
    if annual_periods:
        latest = max(annual_periods)
        required = {"营收", "营收同比", "毛利率", "营业利润率", "净利率", "自由现金流", "经营现金流/净利润"}
        available = {m.name for m in metrics if m.period == latest and m.status == "verified"}
        if required - available:
            errors.append("最新完整财年缺少核心指标：" + "、".join(sorted(required - available)))
    number_issues = narrative_number_issues(draft, narrative_references(research or {}, analysis or {}, sources, documents or []), metrics)
    if number_issues:
        errors.append(narrative_error(number_issues))
    if not sources:
        errors.append("缺少来源")
    if any(s.published_at and s.published_at > as_of.isoformat() for s in sources):
        errors.append("来源发布时间晚于资料截止日期")
    issues = []
    for stage, result in (("research", research), ("analysis", analysis)):
        if result:
            issues.extend({"stage": stage, "severity": "blocking", "message": gap, "action": "补充可追溯的原文证据，或撤回缺乏证据的结论后重新分析"} for gap in result.get("gaps", []))
            issues.extend({"stage": stage, "severity": "warning", "message": item, "action": "保留在报告的分析局限中；如需扩展结论，可补充资料"} for item in result.get("limitations", []))
    if research and research.get("gaps"):
        errors.append("研究资料存在未解决缺口")
    if analysis and analysis.get("gaps"):
        errors.append("财报分析存在未解决缺口")
    gaps = [m.metric_id for m in metrics if m.status != "verified"]
    issues.extend({"stage": "analysis", "severity": "blocking", "message": f"{m.metric_id}：{m.reason or '指标未核实'}", "action": "检查 SEC 原始数据和计算口径，补齐核心指标"} for m in metrics if m.status != "verified")
    issues.extend({"stage": "validation", "severity": "blocking", "message": error, "action": "检查原始来源和指标口径后重新分析"} for error in errors if error not in {"研究资料存在未解决缺口", "财报分析存在未解决缺口"})
    # Keep metric IDs for compatibility, and expose all narrative gaps separately.
    return {"passed": not errors and not gaps, "errors": errors, "gaps": gaps, "issues": issues, "warnings": [i["message"] for i in issues if i["severity"] == "warning"], "status": "succeeded" if not errors and not gaps else "needs_review"}
