from datetime import date
from types import SimpleNamespace

import pytest

from invest_research.agents import execute_agent
from invest_research.narrative import narrative_number_issues, narrative_references
from invest_research.schemas import DraftResult, RunRequest, Source
from invest_research.storage import Store
from invest_research.validation import validate_report
from invest_research.workflow import RunService


SOURCE = "sec-0000320193-25-000079"
METRIC = "营收-2025"


def draft(text):
    return DraftResult(summary=text, business="业务", developments="进展", financial_analysis="盈利", risks="风险", gaps="缺口")


@pytest.mark.parametrize("text", [
    f"原文（{SOURCE}）", f"[{SOURCE}](#{SOURCE})", f"参考指标 {METRIC}。",
    "依据 10-K、10-Q/A 和 8-K。", "依据10-K披露。", f"See {SOURCE}.", "See 10-K.",
])
def test_known_identifiers_and_forms_are_not_financial_numbers(text):
    assert not narrative_number_issues(draft(text), [SOURCE, METRIC])


@pytest.mark.parametrize("text", [
    f"营收增长 12.5%（{SOURCE}）", "营收为 $123 billion", "营收增长１２％",
    "报告发表于2025年", "未知 sec-0000320193-25-999999",
    f"{SOURCE}9", f"{SOURCE}-123", "营收-20250", "110-K", "10-K123",
])
def test_other_numbers_are_still_flagged_with_context(text):
    issues = narrative_number_issues(draft(text), [SOURCE, METRIC])
    assert issues and issues[0]["field"] == "summary"
    assert issues[0]["number"] in issues[0]["excerpt"]


def test_final_validation_uses_same_reference_policy():
    for text, rejected in [(f"参见 {SOURCE}、{METRIC} 和 10-K。", False), (f"增长12%（{SOURCE}）", True)]:
        result = validate_report("", draft(text), [], [], date(2026, 1, 1), {"source_ids": [SOURCE]}, {"metric_ids": [METRIC]})
        assert any("叙述包含" in error for error in result["errors"]) == rejected


def test_source_catalog_and_filing_model_codes_are_shared_by_both_guardrails(tmp_path):
    historical = Source(source_id='sec-0001045810-22-000036', type='sec_filing', title='SEC 10-K', url='https://www.sec.gov/report', publisher='SEC')
    research = {'source_ids': [SOURCE], 'developments': ['GB300、H20及H200产品的许可要求。']}
    documents = [{'text': 'Production units of GB300. Export license requirements for H20 and H200.'}]
    references = narrative_references(research, {}, [historical], documents)
    value = draft(f'GB300系列与H20产品、H200产品。参见{historical.source_id}。')
    assert not narrative_number_issues(value, references)
    result = validate_report('', value, [], [historical], date(2026, 1, 1), research, {}, documents=documents)
    assert not any('叙述包含' in error for error in result['errors'])

    store = Store(tmp_path)
    run_id = store.create(RunRequest(company_name='Test'))
    store.write(run_id, '01_sources.json', [historical.model_dump(mode='json')])
    store.write(run_id, '01_filing_texts.json', documents)
    def writer(role, prompt, schema, **kwargs):
        assert kwargs['allowed_references'] == references
        assert not narrative_number_issues(value, kwargs['allowed_references'])
        return value
    service = RunService(store=store, agent_runner=writer)
    assert service._writing(run_id, {'legal_name': 'Test'}, research, {}) == value
    service.pool.shutdown()


def test_model_exemptions_require_prior_research_and_filing_and_do_not_hide_amounts():
    research = {'developments': ['H20、GB300、USD45、FY2026。']}
    documents = [{'text': 'H20 GB300 H200 USD45 FY2026'}]
    references = narrative_references(research, {}, [], documents)
    assert references == ['H20', 'GB300']
    assert narrative_number_issues(draft('H200与GB3000产品。'), references)
    assert narrative_number_issues(draft('H20产品营收45亿美元，毛利率12%。'), references)
    for text in ('H20%', 'H20美元', '$H20', 'H20.5', 'H20-123'):
        assert narrative_number_issues(draft(text), references)
    assert narrative_number_issues(draft('H20产品。'), narrative_references(research, {}))


def test_agent_guardrail_records_failed_and_successful_drafts(monkeypatch, tmp_path):
    monkeypatch.setenv("CREWAI_STORAGE_DIR", str(tmp_path))
    from crewai.tasks.task_output import TaskOutput
    attempts = []
    tasks = []

    def task_factory(**kwargs):
        task = SimpleNamespace(**kwargs)
        tasks.append(task)
        return task

    class Crew:
        def __init__(self, **kwargs):
            pass

        def kickoff(self):
            task = tasks[0]
            bad = TaskOutput(description="test", agent="writer", raw="", pydantic=draft(f"营收增长12%（{SOURCE}）"))
            ok, error = task.guardrail(bad)
            assert not ok and "summary" in error and "12" in error
            good = TaskOutput(description="test", agent="writer", raw="", pydantic=draft(f"参见 {SOURCE} 和 10-K。"))
            assert task.guardrail(good) == (True, good)
            return good

    monkeypatch.setenv("CREWAI_MODEL", "gemini/test")
    monkeypatch.setattr("crewai.Agent", lambda **kwargs: None)
    monkeypatch.setattr("crewai.LLM", lambda **kwargs: None)
    monkeypatch.setattr("crewai.Task", task_factory)
    monkeypatch.setattr("crewai.Crew", Crew)
    result = execute_agent("writing", "test", DraftResult, allowed_references=[SOURCE], validation_observer=attempts.append)
    assert SOURCE in result.summary
    assert attempts[0]["issues"] and not attempts[1]["issues"]


def test_failed_writing_attempt_is_saved_without_success_checkpoint(tmp_path):
    store = Store(tmp_path)
    run_id = store.create(RunRequest(company_name="Test"))

    def failing_agent(role, prompt, schema, tools=None, **kwargs):
        assert kwargs["allowed_references"] == [SOURCE, METRIC]
        kwargs["validation_observer"]({"draft": draft("增长12%").model_dump(), "issues": [{"field": "summary"}]})
        raise ValueError("validation failed")

    service = RunService(store=store, agent_runner=failing_agent)
    with pytest.raises(ValueError, match="validation failed"):
        service._writing(run_id, {"legal_name": "Test"}, {"source_ids": [SOURCE]}, {"metric_ids": [METRIC]})
    assert store.read(run_id, "03_writing_validation.json")["attempts"][0]["issues"]
    assert not store.exists(run_id, "03_report_draft.json")
    service.pool.shutdown()


def test_reports_every_number_instead_of_only_first_per_field():
    issues = narrative_number_issues(draft('毛利率从44.13%升至46.91%，比率接近于1。'))
    assert [i['number'] for i in issues] == ['44.13', '46.91', '1']


def test_withdrawal_preserves_citations_and_other_sentences():
    from invest_research.narrative import withdraw_numeric_sentences
    ratio = '经营现金流/净利润-2025'
    original = draft(f'现金流保持稳定。比率接近于1（metric_id: {ratio}），意味着现金转化良好。参见{SOURCE}和10-K。')
    repaired, changes = withdraw_numeric_sentences(original, [SOURCE, ratio])
    assert repaired.summary.startswith('现金流保持稳定。')
    assert ratio in repaired.summary and SOURCE in repaired.summary and '10-K' in repaired.summary
    assert '意味着现金转化良好' not in repaired.summary
    assert '接近' not in repaired.summary
    assert len(changes) == 1
    assert '已撤回对应整句' in repaired.gaps
    assert repaired.business == original.business
    assert not narrative_number_issues(repaired, [SOURCE, ratio])


def test_withdrawal_handles_decimals_unicode_unknown_ids_and_multiple_fields():
    from invest_research.narrative import withdraw_numeric_sentences
    original = draft(f'Growth was 12.5% ({SOURCE}). Stable demand.')
    original.financial_analysis = '毛利率为１２％；营收-2099无法核实。后续内容。'
    repaired, changes = withdraw_numeric_sentences(original, [SOURCE])
    assert len(changes) == 2
    assert 'Stable demand.' in repaired.summary
    assert repaired.financial_analysis.endswith('后续内容。')
    assert '营收-2099' not in repaired.financial_analysis
    assert not narrative_number_issues(repaired, [SOURCE])
    unchanged, changes = withdraw_numeric_sentences(repaired, [SOURCE])
    assert unchanged == repaired and not changes


def test_guardrail_uses_validated_fallback_after_two_unsuccessful_rewrites(monkeypatch, tmp_path):
    from crewai.tasks.task_output import TaskOutput
    monkeypatch.setenv('CREWAI_STORAGE_DIR', str(tmp_path))
    monkeypatch.setenv('CREWAI_MODEL', 'gemini/test')
    attempts, tasks = [], []
    def task_factory(**kwargs):
        task = SimpleNamespace(**kwargs)
        tasks.append(task)
        return task
    class Crew:
        def __init__(self, **kwargs):
            pass
        def kickoff(self):
            task = tasks[0]
            bad = TaskOutput(description='test', agent='writer', raw='', pydantic=draft(f'比率接近于1（{METRIC}）。'))
            assert not task.guardrail(bad)[0]
            assert not task.guardrail(bad)[0]
            ok, result = task.guardrail(bad)
            assert ok
            return TaskOutput(description='test', agent='writer', raw=result, pydantic=DraftResult.model_validate_json(result))
    monkeypatch.setattr('crewai.Agent', lambda **kwargs: None)
    monkeypatch.setattr('crewai.LLM', lambda **kwargs: None)
    monkeypatch.setattr('crewai.Task', task_factory)
    monkeypatch.setattr('crewai.Crew', Crew)
    result = execute_agent('writing', 'test', DraftResult, allowed_references=[METRIC], validation_observer=attempts.append)
    assert len(attempts) == 4
    assert attempts[-1]['repair'] == 'withdraw_numeric_sentences'
    assert attempts[-1]['changes']
    assert not narrative_number_issues(result, [METRIC])
