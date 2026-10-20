import { useState } from 'react'
import type { Metric, Source } from './types'

const annualViews = [
  { label: '营收', names: ['营收'], unit: 'USD' },
  { label: '盈利能力', names: ['毛利率', '营业利润率', '净利率'], unit: '%' },
  { label: '营收增速', names: ['营收同比'], unit: '%' },
  { label: '自由现金流', names: ['自由现金流'], unit: 'USD' },
  { label: '现金流质量', names: ['经营现金流/净利润'], unit: '倍' },
]
const colors = ['#159d89', '#547bcc', '#c58b36']
const isValue = (m: Metric) => m.status === 'verified' && m.value !== null && Number.isFinite(m.value)
const valueText = (value: number, unit: string) => `${(unit === 'USD' ? value / 1e9 : value).toFixed(2)}${unit === '%' ? '%' : unit === 'USD' ? ' 十亿美元' : ' 倍'}`

export function FinancialTrends({ metrics, sources }: { metrics: Metric[]; sources: Source[] }) {
  const [view, setView] = useState(0)
  if (!metrics.length) return null
  return <section className="financial-trends" aria-label="财务趋势">
    <div className="trend-heading"><div><span className="section-number">FINANCIAL TRENDS</span><h2>财务趋势一览</h2></div><span>按时间从早到晚 · 点击数据点查看依据</span></div>
    <div className="trend-grid">
      <div className="card trend-card"><h3>年度趋势</h3><div className="trend-tabs" aria-label="年度指标">{annualViews.map((item, i) => <button key={item.label} aria-pressed={view === i} onClick={() => setView(i)}>{item.label}</button>)}</div>
        <TrendChart key={view} metrics={metrics.filter(m => /^\d{4}$/.test(m.period))} sources={sources} {...annualViews[view]} />
      </div>
      <div className="card trend-card"><h3>季度营收</h3><p className="trend-subtitle">单季金额 · 与年度指标分开展示</p><TrendChart metrics={metrics.filter(m => /^\d{4}Q[1-4]$/.test(m.period))} sources={sources} names={['季度营收']} unit="USD" label="季度营收" bars /></div>
    </div>
    <p className="trend-note">图表沿用报告中已核验的数值；缺失或未核验数据不绘制，断档不连线。完整数值、计算口径和来源仍见下方财务表。</p>
  </section>
}

function TrendChart({ metrics, sources, names, unit, label, bars = false }: {
  metrics: Metric[]; sources: Source[]; names: string[]; unit: string; label: string; bars?: boolean
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const relevant = metrics.filter(m => names.includes(m.name) && m.unit === unit)
  const available = relevant.filter(isValue)
  const periods = [...new Set(metrics.map(m => m.period))].sort()
  const selected = available.find(m => m.metric_id === selectedId) || [...available].sort((a, b) => b.period.localeCompare(a.period))[0]
  if (new Set(available.map(m => m.period)).size < 2) return <div className="trend-empty">至少需要两个期间的已核验数据才能展示趋势。</div>
  // Include absent periods in the timeline so missing quarters/years never join a line.
  const start = Number(periods[0].slice(0, 4)) * (bars ? 4 : 1) + (bars ? Number(periods[0].slice(-1)) - 1 : 0)
  const ordinal = (p: string) => Number(p.slice(0, 4)) * (bars ? 4 : 1) + (bars ? Number(p.slice(-1)) - 1 : 0)
  const end = ordinal(periods[periods.length - 1])
  const x = (period: string) => 62 + (ordinal(period) - start) / Math.max(1, end - start) * 410
  const values = available.map(m => m.value!)
  const low = Math.min(0, ...values)
  const high = Math.max(0, ...values)
  const padding = (high - low || 1) * .18
  const min = low < 0 ? low - padding : 0
  const max = high + padding
  const y = (value: number) => 190 - (value - min) / (max - min) * 158
  const tick = (value: number) => `${(unit === 'USD' ? value / 1e9 : value).toFixed(unit === '倍' ? 1 : 0)}${unit === '%' ? '%' : ''}`
  return <>
    <div className="trend-legend">{names.map((name, i) => <span key={name}><i style={{ background: colors[i] }} />{name}</span>)}<small>{unit === 'USD' ? '单位：十亿美元' : `单位：${unit}`}</small></div>
    <div className="trend-plot"><svg viewBox="0 0 530 232" role="group" aria-label={`${label}趋势图`}>
      {[0, 1, 2, 3, 4].map(i => { const v = min + (max - min) * i / 4; return <g key={i}><line x1="52" x2="492" y1={y(v)} y2={y(v)} stroke="#e7eeef" /><text x="43" y={y(v) + 4} textAnchor="end">{tick(v)}</text></g> })}
      {min < 0 && <line x1="52" x2="492" y1={y(0)} y2={y(0)} stroke="#97a9b0" />}
      {periods.map(period => <text key={period} x={x(period)} y="218" textAnchor="middle">{period}</text>)}
      {names.map((name, index) => {
        const points = available.filter(m => m.name === name).sort((a, b) => a.period.localeCompare(b.period))
        const path = points.map((m, i) => `${i && ordinal(m.period) - ordinal(points[i - 1].period) === 1 ? 'L' : 'M'} ${x(m.period)} ${y(m.value!)}`).join(' ')
        return <g key={name}>
          {!bars && <path d={path} fill="none" stroke={colors[index]} strokeWidth="2.5" />}
          {points.map(m => <g key={m.metric_id} role="button" tabIndex={0} aria-label={`${m.period} ${m.name} ${valueText(m.value!, unit)}，查看计算口径和来源`} className={`trend-point ${selected.metric_id === m.metric_id ? 'selected' : ''}`} onClick={() => setSelectedId(m.metric_id)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedId(m.metric_id) } }}>
            <title>{`${m.period} ${m.name}：${valueText(m.value!, unit)}\n${m.formula}`}</title>
            {bars ? <rect x={x(m.period) - 23} y={Math.min(y(m.value!), y(0))} width="46" height={Math.max(2, Math.abs(y(m.value!) - y(0)))} rx="4" fill={colors[index]} opacity={selected.metric_id === m.metric_id ? 1 : .65} /> : <><circle cx={x(m.period)} cy={y(m.value!)} r="12" fill="transparent" /><circle cx={x(m.period)} cy={y(m.value!)} r={selected.metric_id === m.metric_id ? 6 : 4} fill="white" stroke={colors[index]} strokeWidth="2.5" /></>}
            {bars && <text x={x(m.period)} y={m.value! >= 0 ? y(m.value!) - 9 : y(m.value!) + 16} textAnchor="middle" className="bar-value">{(m.value! / 1e9).toFixed(2)}</text>}
          </g>)}
        </g>
      })}
    </svg></div>
    <div className="trend-detail" aria-live="polite"><div><span>{selected.period} · {selected.name}</span><strong>{valueText(selected.value!, unit)}</strong></div><p>计算口径：{selected.formula}</p><div className="trend-sources"><span>来源</span>{selected.source_ids.map(id => { const source = sources.find(s => s.source_id === id); return source ? <a href={source.url} target="_blank" rel="noreferrer" key={id}>{source.title} ↗</a> : <span key={id}>{id}</span> })}</div></div>
  </>
}
