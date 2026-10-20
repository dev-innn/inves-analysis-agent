from datetime import date

from invest_research.schemas import AnalysisResult, Candidate, DraftResult, ResearchResult, RunRequest, Source
from invest_research.storage import Store
from invest_research.workflow import RunService


class FakeSec:
    def candidates(self, company_name, ticker):
        return [Candidate(cik=1, ticker="TEST", legal_name="Test Company")]

    def filings(self, cik, as_of):
        return [{"form": "10-K", "accession": "0000000001-25-000001", "filed_at": "2025-02-01", "url": "https://www.sec.gov/Archives/edgar/data/1/000000000125000001/report.html", "primary_document": "report.html"}]

    def filing_source(self, filing):
        return Source(source_id="sec-0000000001-25-000001", type="sec_filing", title="SEC 10-K", url=filing["url"], publisher="SEC", accession=filing["accession"])

    def download_filing(self, url):
        import hashlib
        content = ("<html><body>Business: Test Company sells equipment. Risk Factors: competition. Management's Discussion: cash flows remain positive. " * 8 + "</body></html>").encode()
        return content, hashlib.sha256(content).hexdigest()

    def company_facts(self, cik):
        row = {"val": 100, "start": "2024-01-01", "end": "2024-12-31", "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-02-01", "accn": "0000000001-25-000001"}
        return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [row]}}}}}


class FakeSearch:
    def search(self, query, as_of):
        return "[web-1] Test Company IR Public sources reviewed\n[web-2] Test Company News", [
            Source(source_id="web-1", type="web", title="Test Company IR", url="https://example.com/ir", publisher="Company"),
            Source(source_id="web-2", type="web", title="Test Company News", url="https://example.com/news", publisher="News"),
        ]


def fake_agent(role, prompt, schema, tools=None, **kwargs):
    assert tools
    if role == "research":
        assert "Public sources reviewed" in prompt
        assert any(tool.__name__ == "web_search" for tool in tools)
        return ResearchResult(company_summary="业务概况", developments=["公开资料"], risks=["竞争"], source_ids=["web-1", "web-2", "sec-0000000001-25-000001"])
    if role == "analysis":
        return AnalysisResult(profitability="盈利情况待核验", cash_flow="现金流待核验", trends=["增长"], risks=["波动"], metric_ids=["营收-2024"])
    return DraftResult(summary="摘要", business="业务概况", developments="经营进展", financial_analysis="盈利情况待核验", risks="竞争风险", gaps="部分财务指标未披露")


def test_pipeline_persists_outputs_and_marks_gaps(tmp_path):
    store = Store(tmp_path)
    service = RunService(store=store, sec_factory=FakeSec, search_factory=FakeSearch, agent_runner=fake_agent)
    run_id = store.create(RunRequest(company_name="Test Company", as_of_date=date(2025, 3, 1)))
    service.run(run_id)
    row = store.get(run_id)
    assert row["status"] == "needs_review"
    assert all(stage["status"] in {"succeeded", "needs_review"} for stage in row["stages"])
    assert "SEC 10-K" in store.read(run_id, "report.md")
    assert store.read(run_id, "04_validation.json")["gaps"]
    assert any(event["tool"] == "FakeSearch" for event in row["events"])
    assert store.read(run_id, "01_search_results.json")[0]["query"].startswith('"Test Company"')
    service.run(run_id)
    assert store.get(run_id)["status"] == "needs_review"


def test_ambiguous_identity_waits_for_input(tmp_path):
    class Ambiguous(FakeSec):
        def candidates(self, company_name, ticker):
            return [Candidate(cik=1, ticker="ONE", legal_name="One"), Candidate(cik=2, ticker="TWO", legal_name="Two")]

    store = Store(tmp_path)
    service = RunService(store=store, sec_factory=Ambiguous, search_factory=FakeSearch, agent_runner=fake_agent)
    run_id = store.create(RunRequest(company_name="Test Company"))
    service.run(run_id)
    assert store.get(run_id)["status"] == "needs_input"
    assert len(store.get(run_id)["candidates"]) == 2
