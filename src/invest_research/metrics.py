from __future__ import annotations

from datetime import date, timedelta
import hashlib

from .schemas import Fact, Metric, Source


CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "cost": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "operating_cash": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
}


def _fact_id(concept: str, row: dict) -> str:
    key = "|".join(str(row.get(k, "")) for k in ("accn", "start", "end", "val", "filed"))
    return hashlib.sha256(f"{concept}|{key}".encode()).hexdigest()[:16]


def extract_facts(company_facts: dict, as_of: date, cik: int) -> tuple[list[Fact], list[Source]]:
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    facts: list[Fact] = []
    sources: dict[str, Source] = {}
    for name, aliases in CONCEPTS.items():
        for concept in aliases:
            item = us_gaap.get(concept)
            if not item:
                continue
            for row in item.get("units", {}).get("USD", []):
                if row.get("form") not in {"10-K", "10-Q"} or row.get("filed", "9999") > as_of.isoformat() or not row.get("start") or row.get("end", "9999") > as_of.isoformat():
                    continue
                accession = row.get("accn", "")
                if not accession:
                    continue
                source_id = f"sec-{accession}"
                if source_id not in sources:
                    sources[source_id] = Source(source_id=source_id, type="sec_xbrl", title=f"SEC {row['form']} {row['filed']} · XBRL 申报", url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.html", publisher="SEC", published_at=row["filed"], accession=accession)
                facts.append(Fact(fact_id=_fact_id(concept, row), name=name, value=float(row["val"]), unit="USD", start=row["start"], end=row["end"], fy=row.get("fy"), fp=row.get("fp"), form=row["form"], filed_at=row["filed"], accession=accession, source_id=source_id, taxonomy="us-gaap", concept=concept))
    return facts, list(sources.values())


def _duration(fact: Fact) -> int:
    return (date.fromisoformat(fact.end) - date.fromisoformat(fact.start or fact.end)).days


def _latest(rows: list[Fact]) -> Fact | None:
    # Prefer the latest filing, then the preferred concept for that period.
    return max(rows, key=lambda f: (f.filed_at, f.accession, -CONCEPTS[f.name].index(f.concept))) if rows else None


def _calendar(facts: list[Fact]) -> dict[int, tuple[str, str]]:
    annual = [f for f in facts if f.form == "10-K" and f.fp == "FY" and f.fy and 330 <= _duration(f) <= 380]
    ends = {}
    for f in annual:
        ends[f.accession] = max(ends.get(f.accession, ""), f.end)
    calendar = {}
    for f in sorted(annual, key=lambda f: f.filed_at):
        # fy belongs to the filing, not necessarily the comparative fact.
        year = f.fy - (int(ends[f.accession][:4]) - int(f.end[:4]))
        calendar[year] = (f.start, f.end)
    if calendar:
        year = max(calendar)
        start, end = calendar[year]
        # A provisional next fiscal year is sufficient to classify Q1-Q3.
        next_start = date.fromisoformat(end) + timedelta(days=1)
        calendar[year + 1] = (next_start.isoformat(), (next_start + timedelta(days=370)).isoformat())
    return calendar


def select_annual(facts: list[Fact], name: str, year: int) -> Fact | None:
    bounds = _calendar(facts).get(year)
    return _latest([f for f in facts if f.name == name and bounds and (f.start, f.end) == bounds and 330 <= _duration(f) <= 380])


def _quarter_rows(facts: list[Fact], name: str, year: int, quarter: int, ytd: bool) -> list[Fact]:
    bounds = _calendar(facts).get(year)
    if not bounds:
        return []
    start, end = map(date.fromisoformat, bounds)
    rows = []
    for f in facts:
        if f.name != name:
            continue
        elapsed = (date.fromisoformat(f.end) - start).days
        low, high = {1: (75, 110), 2: (160, 210), 3: (245, 300), 4: (330, 380)}[quarter]
        if not low <= elapsed <= high or date.fromisoformat(f.end) > end:
            continue
        if (ytd and f.start == bounds[0]) or (not ytd and 75 <= _duration(f) <= 110):
            rows.append(f)
    return rows


def select_quarter(facts: list[Fact], name: str, year: int, quarter: int) -> Fact | None:
    return _latest(_quarter_rows(facts, name, year, quarter, False))


def select_ytd(facts: list[Fact], name: str, year: int, quarter: int) -> Fact | None:
    return _latest(_quarter_rows(facts, name, year, quarter, True))


def quarter_revenue(facts: list[Fact], year: int, quarter: int) -> Metric:
    period = f"{year}Q{quarter}"
    direct = select_quarter(facts, "revenue", year, quarter)
    if direct:
        return _metric("季度营收", period, "SEC 单季营收原始事实", [direct], "USD", lambda x: x.value)
    current = select_annual(facts, "revenue", year) if quarter == 4 else select_ytd(facts, "revenue", year, quarter)
    previous = select_ytd(facts, "revenue", year, quarter - 1) if quarter > 1 else None
    if current and previous and current.start == previous.start:
        days = (date.fromisoformat(current.end) - date.fromisoformat(previous.end)).days
        if 75 <= days <= 110:
            return _metric("季度营收", period, "同一财年累计营收之差", [current, previous], "USD", lambda a, b: a.value - b.value)
    return _metric("季度营收", period, "同一财年单季或累计差额", [None], "USD", lambda x: x.value)


def _metric(name: str, period: str, formula: str, operands: list[Fact | None], unit: str, fn) -> Metric:
    available = [f for f in operands if f is not None]
    source_ids = list(dict.fromkeys(f.source_id for f in available))
    if len(available) != len(operands):
        value, status, reason = None, "unavailable", "当前解析未获得所需期间及口径的数据；需检查标签映射和原始财报，不能据此认定未披露"
    else:
        try:
            value, status, reason = fn(*available), "verified", None
        except ZeroDivisionError:
            value, status, reason = None, "unavailable", "分母为零"
    return Metric(metric_id=f"{name}-{period}", name=name, value=value, unit=unit, period=period, formula=formula, operand_fact_ids=[f.fact_id for f in available], source_ids=source_ids, status=status, reason=reason)


def calculate_metrics(facts: list[Fact], years: int = 3) -> list[Metric]:
    calendar = _calendar(facts)
    revenue_years = sorted((year for year, bounds in calendar.items() if any(
        f.form == "10-K" and (f.start, f.end) == bounds and 330 <= _duration(f) <= 380 for f in facts
    )), reverse=True)
    result: list[Metric] = []
    for year in revenue_years[:years]:
        period = str(year)
        revenue = select_annual(facts, "revenue", year)
        cost = select_annual(facts, "cost", year)
        operating = select_annual(facts, "operating_income", year)
        net = select_annual(facts, "net_income", year)
        cash = select_annual(facts, "operating_cash", year)
        capex = select_annual(facts, "capex", year)
        previous = select_annual(facts, "revenue", year - 1)
        result.extend([
            _metric("营收", period, "SEC 营收原始事实", [revenue], "USD", lambda x: x.value),
            _metric("营收同比", period, "本年营收 / 上年营收 - 1", [revenue, previous], "%", lambda a, b: (a.value / b.value - 1) * 100),
            _metric("毛利率", period, "(营收 - 营业成本) / 营收", [revenue, cost], "%", lambda a, b: (a.value - b.value) / a.value * 100),
            _metric("营业利润率", period, "营业利润 / 营收", [operating, revenue], "%", lambda a, b: a.value / b.value * 100),
            _metric("净利率", period, "净利润 / 营收", [net, revenue], "%", lambda a, b: a.value / b.value * 100),
            _metric("自由现金流", period, "经营现金流 - 资本开支现金流出绝对值" + ("（含软件及其他无形资产购置）" if capex and capex.concept == "PaymentsToAcquireProductiveAssets" else ""), [cash, capex], "USD", lambda a, b: a.value - abs(b.value)),
            _metric("经营现金流/净利润", period, "经营现金流 / 净利润", [cash, net], "倍", lambda a, b: a.value / b.value),
        ])
    candidates = [(year, q) for year in _calendar(facts) for q in range(1, 5)
                  if any(select_quarter(facts, name, year, q) or select_ytd(facts, name, year, q) for name in CONCEPTS)]
    if candidates:
        year, quarter = max(candidates)
        # Require consecutive fiscal quarters; never substitute older Q4s for gaps.
        for _ in range(4):
            result.append(quarter_revenue(facts, year, quarter))
            year, quarter = (year, quarter - 1) if quarter > 1 else (year - 1, 4)
    return result
