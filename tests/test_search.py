import httpx
import pytest

from invest_research.tools.search import GoogleSearchTool, SerpApiSearchTool, search_tool_from_env


def test_serpapi_returns_structured_sources_and_enforces_cutoff():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"organic_results": [
            {"title": "Investor Relations", "link": "https://example.com/ir", "snippet": "Annual report", "source": "Example"},
            {"title": "Investor Relations duplicate", "link": "https://example.com/ir", "snippet": "Duplicate"},
            {"title": "Risk news", "link": "https://news.example.com/story", "snippet": "Risk update"},
            {"title": "Insecure result", "link": "http://example.com/page", "snippet": "Skip"},
        ]})

    search = SerpApiSearchTool("test-key", max_queries=1, transport=httpx.MockTransport(respond))
    summary, sources = search.search("Example Company", "2025-03-01")
    assert requests[0].url.params["q"] == "Example Company before:2025-03-02"
    assert requests[0].url.params["engine"] == "google"
    assert [source.source_id for source in sources] == ["web-1-1", "web-1-2"]
    assert "[web-1-1]" in summary and "Annual report" in summary
    assert "http://example.com/page" not in summary
    with pytest.raises(ValueError, match="budget"):
        search.search("Another query", "2025-03-01")


def test_serpapi_retries_temporary_error_but_not_bad_key(monkeypatch):
    monkeypatch.setattr("invest_research.tools.search.time.sleep", lambda _: None)
    calls = 0

    def temporary(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"organic_results": [{"title": "Source", "link": "https://example.com/source"}]})

    search = SerpApiSearchTool("test-key", transport=httpx.MockTransport(temporary))
    assert len(search.search("query", "2025-03-01")[1]) == 1
    assert calls == 2

    calls = 0

    def unauthorized(request):
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    search = SerpApiSearchTool("invalid-key", transport=httpx.MockTransport(unauthorized))
    with pytest.raises(RuntimeError, match="HTTP 401") as error:
        search.search("query", "2025-03-01")
    assert calls == 1
    assert "invalid-key" not in str(error.value)


def test_search_backend_selection_is_independent_of_agent_model(monkeypatch):
    monkeypatch.setenv("CREWAI_MODEL", "openai/gpt-4o-mini")
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert isinstance(search_tool_from_env(), SerpApiSearchTool)

    monkeypatch.setenv("SEARCH_PROVIDER", "gemini_grounding")
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        search_tool_from_env()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert isinstance(search_tool_from_env(), GoogleSearchTool)

    monkeypatch.setenv("SEARCH_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="SEARCH_PROVIDER"):
        search_tool_from_env()
