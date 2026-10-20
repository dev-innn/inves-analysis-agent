"""Validate a deliberately bounded, explicit numeric citation grammar.

A value is bound to the single metric citation immediately following its unit.
Unrecognised or ambiguous prose fails closed rather than matching any number
elsewhere in a report. This is not a general natural-language fact checker.
"""
from __future__ import annotations

import re
from decimal import Decimal

from .schemas import Metric

NUMBER = re.compile(r"[+\-−]?\d+(?:,\d{3})*(?:\.\d+)?")
UNIT = r"十亿美元|亿美元|百万美元|万美元|美元|USD|%|％|个百分点|倍"
CITATION = re.compile(r"\s*(?P<unit>" + UNIT + r")?\s*[（(]\s*(?:metric_ids?\s*[:：]\s*)?(?P<id>[^()（）]+?)\s*[）)]")
TRANSLATION = str.maketrans('０１２３４５６７８９％－＋．，', '0123456789%-+.,')
SCALES = {'美元': 1, 'USD': 1, '万美元': 10000, '百万美元': 1000000, '亿美元': 100000000, '十亿美元': 1000000000}
ALIASES = {
    '营收同比': ('营收同比', '营收增长率', '收入增长率', '营收增长', '收入增长'),
    '营业利润率': ('营业利润率', '运营利润率'),
    '净利率': ('净利率', '净利润率'),
    '毛利率': ('毛利率',),
    '自由现金流': ('自由现金流',),
    '经营现金流/净利润': ('经营现金流/净利润', '经营现金流量与净利润比率', '经营现金流与净利润比率'),
    '季度营收': ('季度营收', '季度收入'),
    '营收': ('营收', '收入'),
}


def numeric_checks(text: str, masked: str, metrics: list[Metric]) -> list[dict]:
    """Return a reason (empty on success) for every unmasked number."""
    text, masked = text.translate(TRANSLATION), masked.translate(TRANSLATION)
    by_id = {m.metric_id: m for m in metrics if m.status == 'verified' and m.value is not None}
    matches = list(NUMBER.finditer(masked))
    checks = []
    bindings = {}
    for match in matches:
        if re.search(r'\d{4}Q$', text[:match.start()]):
            continue
        # Calendar labels are checked separately against the bound metric below.
        if re.match(r'(?:年|Q[1-4])', text[match.end():]):
            continue
        tail = CITATION.match(text, match.end())
        reason = '数字后须紧跟单位及唯一指标引用，例如 6.43%（metric_id: 营收同比-2025）'
        if tail and tail['id'] in by_id:
            metric = by_id[tail['id']]
            bindings[match.start()] = metric
            unit = tail['unit'] or ''
            before = text[max(0, match.start()-100):match.start()]
            clause = re.split(r'[，,；;。！？\n]', before)[-1]
            approximate = bool(re.search(r'(?:接近于?|约为?|大约)\s*$', clause))
            actual = Decimal(str(metric.value))
            value = Decimal(match.group().replace(',', '').replace('−', '-'))
            scale = Decimal(1)
            reason = ''
            if metric.unit == 'USD':
                if re.search(r'人民币|欧元|港元|日元|CNY|EUR|HKD|JPY', clause):
                    reason = '币种与美元指标不一致'
                elif unit not in SCALES:
                    reason = '金额须明确使用美元及数量级单位'
                else:
                    scale = Decimal(SCALES[unit])
            elif metric.unit == '%':
                if unit != '%':
                    reason = '百分比指标须用 %，不能与倍数或百分点混用'
            elif metric.unit == '倍':
                if unit != '倍' and not (not unit and approximate):
                    reason = '比率须使用倍；接近或约为表述可省略倍'
            else:
                reason = '暂不支持该指标单位的正文数值'
            if not reason:
                expected = actual / scale
                places = max(0, -value.as_tuple().exponent)
                tolerance = Decimal('0.5') * Decimal(10) ** -places
                if approximate:
                    # Approximation must be close, not merely round to an integer.
                    tolerance = min(tolerance, max(abs(expected) * Decimal('0.01'), Decimal('0.000001')))
                if abs(value - expected) > tolerance + Decimal('0.000000001') or (value != 0 and value * expected < 0):
                    reason = f'数值与 {metric.metric_id} 不符（含单位换算及舍入）'
                if not reason and metric.name.endswith('同比') and expected < 0 and re.search(r'增长|上升|增加|提升', clause):
                    reason = '增长表述与负值指标矛盾'
                if not reason and expected > 0 and re.search(r'下降|减少|下滑', clause):
                    reason = '下降表述与正值指标矛盾；跨期比较须改为明确列示各期值'
                if not reason and not metric.name.endswith('同比') and re.search(r'增长|上升|增加|提升|下降|减少|下滑|升至|降至', clause):
                    reason = '趋势表述需要同时引用可比较的前后期指标'
            # Longest names first prevents 营收 masking 营收同比/季度营收.
            names = sorted(((alias, name) for name, aliases in ALIASES.items() for alias in aliases), key=lambda x: -len(x[0]))
            for alias, name in names:
                if alias in clause:
                    if name != metric.name:
                        reason = f'指标名称与引用不一致：{alias} / {metric.name}'
                    break
            years = re.findall(r'(?<!\d)(\d{4})年', clause)
            quarters = re.findall(r'(\d{4}Q[1-4])', clause)
            if any(y != metric.period for y in years) or any(q != metric.period for q in quarters):
                reason = '正文期间与所引用指标期间不一致'
        checks.append({'start': match.start(), 'end': match.end(), 'number': match.group(), 'reason': reason})
    bound_positions = list(bindings)
    for left, right in zip(bound_positions, bound_positions[1:]):
        between = text[left:right]
        direction = re.search(r'(?:上升|增长|增加|提升|下降|减少|下滑|升|降)(?:至|到|为)', between)
        if not direction or re.search(r'[。！？!?\n]', between):
            continue
        first, second = bindings[left], bindings[right]
        comparable = first.name == second.name and first.unit == second.unit and first.period < second.period
        up = direction.group().startswith(('上升', '增长', '增加', '提升', '升'))
        correct = comparable and ((second.value > first.value) if up else (second.value < first.value))
        target = next(c for c in checks if c['start'] == right)
        if not correct:
            target['reason'] = '跨期趋势与引用指标的期间、口径或变化方向不一致'
        elif target['reason'].startswith(('下降表述与正值指标矛盾', '趋势表述需要')):
            target['reason'] = ''
    # Years are allowed only as a prefix in the same clause as a verified value.
    for match in matches:
        if not re.match(r'(?:年|Q[1-4])', text[match.end():]):
            continue
        next_binding = next(((pos, m) for pos, m in bindings.items() if pos > match.end() and not re.search(r'[，,；;。！？\n]', text[match.end():pos])), None)
        period = match.group()
        suffix = re.match(r'Q[1-4]', text[match.end():])
        if suffix:
            period += suffix.group()
        reason = '' if next_binding and period == next_binding[1].period else '年份/季度必须与同一分句中紧邻的已核验指标一致'
        checks.append({'start': match.start(), 'end': match.end(), 'number': match.group(), 'reason': reason})
    return sorted(checks, key=lambda x: x['start'])
