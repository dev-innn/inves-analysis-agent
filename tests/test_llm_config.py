import pytest

from invest_research.agents import llm_options_from_env


def test_gemini_configuration_keeps_existing_behavior(monkeypatch):
    monkeypatch.setenv("CREWAI_MODEL", "gemini/gemini-2.5-flash")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm_options_from_env() == {"model": "gemini/gemini-2.5-flash"}


def test_openai_configuration_passes_only_selected_options(monkeypatch):
    monkeypatch.setenv("CREWAI_MODEL", "openai/example-model")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_MAX_COMPLETION_TOKENS", "4000")
    monkeypatch.setenv("OPENAI_TIMEOUT", "45")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "3")
    for name in ("OPENAI_REASONING_EFFORT", "OPENAI_BASE_URL", "OPENAI_ORGANIZATION", "OPENAI_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    options = llm_options_from_env()
    assert options == {
        "model": "openai/example-model",
        "api_key": "test-key",
        "api": "responses",
        "timeout": 45.0,
        "max_retries": 3,
        "max_completion_tokens": 4000,
    }


def test_openai_requires_key_and_valid_mode(monkeypatch):
    monkeypatch.setenv("CREWAI_MODEL", "openai/example-model")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        llm_options_from_env()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_MODE", "invalid")
    with pytest.raises(ValueError, match="OPENAI_API_MODE"):
        llm_options_from_env()
