import pytest
from invest_research.schemas import Metric, DraftResult
from invest_research.narrative import narrative_number_issues, withdraw_numeric_sentences


def metric(name, value, unit, period='2025', status='verified'):
    return Metric(metric_id=f'{name}-{period}', name=name, value=value, unit=unit, period=period, status=status, formula='test', operand_fact_ids=[], source_ids=['sec-1'])


METRICS = [metric('营收',416161000000,'USD'), metric('营收同比',6.42551178,'%'), metric('毛利率',46.905164,'%'), metric('经营现金流/净利润',0.995,'倍'), metric('季度营收',100000000,'USD','2025Q1'),metric('毛利率',44.13,'%','2023')]

def check(text, metrics=METRICS):
    draft = DraftResult(summary=text,business='业务',developments='进展',financial_analysis='盈利',risks='风险',gaps='局限')
    return narrative_number_issues(draft, [], metrics)


@pytest.mark.parametrize('text',[
    '2025年营收为4161.61亿美元（metric_id: 营收-2025）。',
    '营收为416.16十亿美元（营收-2025）。',
    '营收为416,161,000,000美元（营收-2025）。',
    '营收同比为6.43%（metric_id: 营收同比-2025）。',
    '营收同比为６.４３％（营收同比-2025）。',
    '经营现金流量与净利润比率接近于1（metric_id: 经营现金流/净利润-2025）。',
    '经营现金流/净利润为0.995倍（经营现金流/净利润-2025）。',
    '2025Q1季度营收为1亿美元（季度营收-2025Q1）。',
    '毛利率从44.13%（毛利率-2023）上升至46.91%（毛利率-2025）。',
])
def test_verified_narrative_values(text):
    assert not check(text)


@pytest.mark.parametrize('text',[
    '2024年营收为4161.61亿美元（营收-2025）。',
    '2025年季度营收为1亿美元（季度营收-2025Q1）。',
    '净利率为46.91%（毛利率-2025）。',
    '营收为4161.61美元（营收-2025）。',
    '人民币营收为4161.61亿美元（营收-2025）。',
    '营收同比为6.43个百分点（营收同比-2025）。',
    '营收同比为6.43倍（营收同比-2025）。',
    '营收同比为99%（营收同比-2025）。',
    '营收同比下降6.43%（营收同比-2025）。',
    '经营现金流/净利润接近于2（经营现金流/净利润-2025）。',
    '营收同比为6.43%（sec-1）。',
    '营收同比为6.43%。',
    '毛利率从44.13%（毛利率-2023）下降至46.91%（毛利率-2025）。',
    '营收同比为6.43%（营收同比-2025、毛利率-2025）。',
    '营收同比为-6.43%（营收同比-2025）。',
])
def test_wrong_or_unbound_values_fail_closed(text):
    assert check(text)


def test_unverified_metrics_do_not_authorize_numbers():
    assert check('毛利率为46.91%（毛利率-2025）。', [metric('毛利率',46.905164,'% ', status='needs_review')])


def test_approximation_is_not_integer_rounding():
    assert check('经营现金流/净利润接近1（经营现金流/净利润-2025）。', [metric('经营现金流/净利润',0.6,'倍')])


def test_negative_growth_and_signed_values():
    metrics=[metric('营收同比',-6.4255,'%')]
    assert not check('营收同比为-6.43%（营收同比-2025）。',metrics)
    assert check('营收同比增长-6.43%（营收同比-2025）。',metrics)


def test_fallback_keeps_verified_numeric_sentence():
    original=DraftResult(summary='营收同比为6.43%（营收同比-2025）。毛利率为99%（毛利率-2025）。',business='业务',developments='进展',financial_analysis='盈利',risks='风险',gaps='局限')
    repaired,changes=withdraw_numeric_sentences(original,[],METRICS)
    assert '6.43%' in repaired.summary
    assert '99%' not in repaired.summary
    assert len(changes)==1
    assert not narrative_number_issues(repaired,[],METRICS)


@pytest.mark.parametrize('text',[
    '毛利率上升至46.91%（毛利率-2025）。',
    '毛利率从44.13%（毛利率-2023）下降到46.91%（毛利率-2025）。',
    '毛利率从44.13%（毛利率-2023）上升至99%（毛利率-2025）。',
])
def test_trends_cannot_hide_wrong_values_or_missing_baselines(text):
    assert check(text)


def test_guardrail_and_final_validation_share_metrics(monkeypatch, tmp_path):
    from datetime import date
    from types import SimpleNamespace
    from crewai.tasks.task_output import TaskOutput
    from invest_research.agents import execute_agent
    from invest_research.validation import validate_report
    monkeypatch.setenv('CREWAI_STORAGE_DIR', str(tmp_path))
    monkeypatch.setenv('CREWAI_MODEL', 'gemini/test')
    text='经营现金流量与净利润比率接近于1（经营现金流/净利润-2025）。'
    value=DraftResult(summary='摘要',business='业务',developments='进展',financial_analysis=text,risks='风险',gaps='局限')
    tasks=[]
    def task_factory(**kwargs):
        task=SimpleNamespace(**kwargs);tasks.append(task);return task
    class Crew:
        def __init__(self,**kwargs):pass
        def kickoff(self):
            result=TaskOutput(description='test',agent='writer',raw='',pydantic=value)
            assert tasks[0].guardrail(result)==(True,result)
            return result
    monkeypatch.setattr('crewai.Agent',lambda **kwargs:None)
    monkeypatch.setattr('crewai.LLM',lambda **kwargs:None)
    monkeypatch.setattr('crewai.Task',task_factory)
    monkeypatch.setattr('crewai.Crew',Crew)
    output=execute_agent('writing','test',DraftResult,verified_metrics=[m.model_dump() for m in METRICS])
    assert output==value
    validation=validate_report('',output,METRICS,[],date(2026,1,1))
    assert not any('叙述包含' in e for e in validation['errors'])
