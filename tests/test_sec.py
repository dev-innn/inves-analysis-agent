from datetime import date

import httpx

from invest_research.tools.sec import SecClient


def test_sec_resolves_ticker_and_builds_filing_url(monkeypatch):
    monkeypatch.setattr("invest_research.tools.sec.time.sleep", lambda _: None)
    SecClient._cache.clear()
    seen_agents = []

    def handler(request):
        seen_agents.append(request.headers.get("User-Agent"))
        if request.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})
        return httpx.Response(200, json={"filings": {"recent": {"form": ["10-K", "8-K"], "filingDate": ["2024-11-01", "2024-11-02"], "accessionNumber": ["0000320193-24-000123", "0000320193-24-000124"], "primaryDocument": ["annual.htm", "event.htm"]}}})

    sec = SecClient("Research Team research@example.com", transport=httpx.MockTransport(handler))
    assert sec.candidates("Apple", "AAPL")[0].cik == 320193
    filings = sec.filings(320193, date(2024, 12, 1))
    assert len(filings) == 1
    assert filings[0]["url"].endswith("/000032019324000123/annual.htm")
    assert all(agent == "Research Team research@example.com" for agent in seen_agents)
