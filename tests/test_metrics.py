from datetime import date

from invest_research.metrics import calculate_metrics, extract_facts


def entry(value, start, end, year, accession):
    return {"val": value, "start": start, "end": end, "fy": year, "fp": "FY", "form": "10-K", "filed": f"{year + 1}-02-01", "accn": accession}


def test_annual_metrics_keep_operand_sources():
    data = {"facts": {"us-gaap": {}}}
    values = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": (200, 100),
        "CostOfRevenue": (80, 50),
        "OperatingIncomeLoss": (60, 20),
        "NetIncomeLoss": (40, 10),
        "NetCashProvidedByUsedInOperatingActivities": (50, 25),
        "PaymentsToAcquirePropertyPlantAndEquipment": (10, 5),
    }
    for concept, (current, previous) in values.items():
        data["facts"]["us-gaap"][concept] = {"units": {"USD": [entry(current, "2024-01-01", "2024-12-31", 2024, "0000000001-25-000001"), entry(previous, "2023-01-01", "2023-12-31", 2023, "0000000001-24-000001")]}}
    facts, sources = extract_facts(data, date(2025, 3, 1), 1)
    metrics = calculate_metrics(facts, 2)
    index = {(m.name, m.period): m for m in metrics}
    assert index[("营收同比", "2024")].value == 100
    assert index[("毛利率", "2024")].value == 60
    assert index[("自由现金流", "2024")].value == 40
    assert len(index[("营收同比", "2024")].operand_fact_ids) == 2
    assert set(index[("营收同比", "2024")].source_ids) == {s.source_id for s in sources}


def test_missing_data_is_unavailable():
    facts, _ = extract_facts({"facts": {"us-gaap": {"Revenues": {"units": {"USD": [entry(100, "2024-01-01", "2024-12-31", 2024, "0000000001-25-000001")]}}}}}, date(2025, 3, 1), 1)
    metrics = calculate_metrics(facts)
    margin = next(m for m in metrics if m.name == "毛利率")
    assert margin.status == "unavailable" and margin.value is None


def test_alias_migration_and_consecutive_quarters():
    def row(value, start, end, fy, fp, filed, accn):
        return dict(val=value, start=start, end=end, fy=fy, fp=fp, filed=filed, accn=accn, form='10-K' if fp == 'FY' else '10-Q')
    old = row(100, '2022-01-01', '2022-12-31', 2022, 'FY', '2023-02-01', 'old')
    annual = row(400, '2024-01-01', '2024-12-31', 2024, 'FY', '2025-02-01', 'annual')
    q3 = row(280, '2024-01-01', '2024-09-30', 2024, 'Q3', '2024-11-01', 'q3')
    q1 = row(110, '2025-01-01', '2025-03-31', 2025, 'Q1', '2025-05-01', 'q1')
    q2 = row(230, '2025-01-01', '2025-06-30', 2025, 'Q2', '2025-08-01', 'q2')
    # A comparative quarter in a newer filing must retain its actual period.
    comparative = row(90, '2024-04-01', '2024-06-30', 2025, 'Q2', '2025-08-01', 'q2')
    data = {'facts': {'us-gaap': {
        'RevenueFromContractWithCustomerExcludingAssessedTax': {'units': {'USD': [old]}},
        'RevenueFromContractWithCustomerIncludingAssessedTax': {'units': {'USD': [annual, q3, q1, q2, comparative]}},
    }}}
    facts, _ = extract_facts(data, date(2025, 9, 1), 1)
    quarters = [m for m in calculate_metrics(facts) if m.name == '季度营收']
    assert [m.period for m in quarters] == ['2025Q2', '2025Q1', '2024Q4', '2024Q3']
    assert [m.value for m in quarters[:3]] == [120, 110, 120]
    assert quarters[3].status == 'unavailable'
    assert max(m.period for m in calculate_metrics(facts) if m.name == '营收') == '2024'


def test_non_calendar_fiscal_year_and_comparatives():
    data = {'facts': {'us-gaap': {'Revenues': {'units': {'USD': [
        dict(val=400, start='2023-10-01', end='2024-09-28', fy=2024, fp='FY', form='10-K', filed='2024-11-01', accn='a'),
        dict(val=300, start='2022-09-25', end='2023-09-30', fy=2024, fp='FY', form='10-K', filed='2024-11-01', accn='a'),
        dict(val=290, start='2023-10-01', end='2024-06-29', fy=2024, fp='Q3', form='10-Q', filed='2024-08-01', accn='q'),
        dict(val=120, start='2024-09-29', end='2024-12-28', fy=2025, fp='Q1', form='10-Q', filed='2025-02-01', accn='b'),
    ]}}}}}
    facts, _ = extract_facts(data, date(2025, 3, 1), 1)
    ms = {m.metric_id: m for m in calculate_metrics(facts)}
    assert ms['营收-2023'].value == 300
    assert ms['季度营收-2025Q1'].value == 120
    assert ms['季度营收-2024Q4'].value == 110


def test_future_periods_are_excluded():
    data = {'facts': {'us-gaap': {'Revenues': {'units': {'USD': [entry(100, '2024-01-01', '2026-12-31', 2024, 'a')]}}}}}
    facts, _ = extract_facts(data, date(2025, 3, 1), 1)
    assert not facts


def test_sec_real_company_regressions():
    import json
    from pathlib import Path
    expected = {
        'nvda': ('2026', 96676000000, ['2027Q2', '2027Q1', '2026Q4', '2026Q3']),
        'aapl': ('2025', 98767000000, ['2026Q3', '2026Q2', '2026Q1', '2025Q4']),
        'msft': ('2026', 66987000000, ['2026Q4', '2026Q3', '2026Q2', '2026Q1']),
    }
    for ticker, (year, fcf, quarters) in expected.items():
        data = json.loads((Path(__file__).parent / 'fixtures' / f'{ticker}_companyfacts.json').read_text())
        facts, _ = extract_facts(data, date(2026, 10, 18), 1)
        metrics = calculate_metrics(facts)
        assert all(m.status == 'verified' for m in metrics), ticker
        assert next(m.value for m in metrics if m.metric_id == f'自由现金流-{year}') == fcf
        assert [m.period for m in metrics if m.name == '季度营收'] == quarters
        if ticker == 'nvda':
            assert '无形资产' in next(m.formula for m in metrics if m.name == '自由现金流')


def test_stale_revenue_cannot_hide_newer_filing_periods():
    data = {'facts': {'us-gaap': {
        'Revenues': {'units': {'USD': [entry(100, '2023-01-01', '2023-12-31', 2023, 'a')]}},
        'NetIncomeLoss': {'units': {'USD': [entry(50, '2024-01-01', '2024-12-31', 2024, 'b')]}},
    }}}
    facts, _ = extract_facts(data, date(2025, 3, 1), 1)
    ms = {m.metric_id: m for m in calculate_metrics(facts)}
    assert ms['营收-2024'].status == 'unavailable'
    assert ms['季度营收-2024Q4'].status == 'unavailable'
    assert '季度营收-2023Q4' not in ms
