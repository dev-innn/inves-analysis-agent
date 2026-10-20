import React from 'react'
import ReactDOM from 'react-dom/client'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useEffect, useState } from 'react'
import { api } from './api'
import { FinancialTrends } from './FinancialTrends'
import type { Artifacts, Metric, Run, RunStatus, Source, Issue, Supplement } from './types'
import './style.css'

const stageNames: Record<string, string> = { identity: '公司身份确认', research: '信息搜集 Agent', analysis: '财报分析 Agent', writing: '报告撰写 Agent', validation: '质量校验' }
const statusNames: Record<RunStatus, string> = { queued: '排队中', running: '运行中', needs_input: '等待选择', needs_review: '需人工复核', succeeded: '已完成', failed: '失败' }
const terminal = new Set<RunStatus>(['needs_review', 'succeeded', 'failed'])
const today = new Date().toISOString().slice(0, 10)

function navigate(path: string) { window.history.pushState({}, '', path); window.dispatchEvent(new PopStateEvent('popstate')) }
function usePath() { const [path, setPath] = useState(location.pathname); useEffect(() => { const handler = () => setPath(location.pathname); window.addEventListener('popstate', handler); return () => window.removeEventListener('popstate', handler) }, []); return path }
function dateTime(value?: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }) : '—' }
function formatMetric(metric: Metric) { if (metric.value === null) return '未披露'; if (metric.unit === 'USD') return `${(metric.value / 1e9).toFixed(2)} 十亿美元`; if (metric.unit === '%') return `${metric.value.toFixed(2)}%`; return `${metric.value.toFixed(2)} 倍` }

function App() {
  const path = usePath()
  const parts = path.split('/').filter(Boolean)
  const runId = parts[0] === 'runs' ? parts[1] : undefined
  return <div className="app-shell">
    <aside className="sidebar">
      <button className="brand" onClick={() => navigate('/')}><span className="brand-mark">R</span><span><strong>ResearchDesk</strong><small>Agent 投研工作台</small></span></button>
      <div className="sidebar-label">工作空间</div>
      <button className={`nav-item ${!runId ? 'active' : ''}`} onClick={() => navigate('/')}><span>◫</span> 新建投研任务</button>
      {runId && <button className={`nav-item ${parts[2] !== 'report' ? 'active' : ''}`} onClick={() => navigate(`/runs/${runId}`)}><span>◷</span> 任务进度</button>}
      {runId && <button className={`nav-item ${parts[2] === 'report' ? 'active' : ''}`} onClick={() => navigate(`/runs/${runId}/report`)}><span>▤</span> 投研报告</button>}
      <div className="sidebar-footer"><span className="live-dot" /> SEC EDGAR · Google Search<br /><small>资料与计算均保留来源</small></div>
    </aside>
    <main className="main-area">
      <header className="topbar"><span>投资研究 / {runId ? parts[2] === 'report' ? '报告' : '任务详情' : '新建任务'}</span><span className="topbar-right">MULTI-AGENT RESEARCH <i /></span></header>
      {runId ? parts[2] === 'report' ? <ReportPage key={runId} id={runId} /> : <RunPage key={runId} id={runId} /> : <HomePage />}
    </main>
  </div>
}

function HomePage() {
  const [company, setCompany] = useState('')
  const [ticker, setTicker] = useState('')
  const [asOf, setAsOf] = useState(today)
  const [periods, setPeriods] = useState(3)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [runs, setRuns] = useState<Run[]>([])
  useEffect(() => { api.list().then(setRuns).catch(() => setRuns([])) }, [])
  async function submit(event: React.FormEvent) { event.preventDefault(); setBusy(true); setError(''); try { const result = await api.create({ company_name: company.trim(), ticker: ticker.trim() || undefined, as_of_date: asOf, report_periods: periods }); navigate(`/runs/${result.run_id}`) } catch (e) { setError((e as Error).message) } finally { setBusy(false) } }
  return <div className="content home">
    <div className="hero"><div className="eyebrow">RESEARCH INTELLIGENCE / 01</div><h1>让研究，从可靠的<br /><em>第一份初稿</em>开始。</h1><p>输入公司名称，三个专业 Agent 将完成资料检索、财报分析与报告撰写。每个数字都能追溯到原始来源。</p><div className="hero-stats"><div><strong>03</strong><span>协作 Agent</span></div><div><strong>05</strong><span>可追踪阶段</span></div><div><strong>SEC</strong><span>财务数据来源</span></div></div></div>
    <div className="grid-home"><section className="card form-card"><div className="card-heading"><div><span className="section-number">01 / 开始研究</span><h2>创建投研任务</h2></div><span className="pill">新任务</span></div><form onSubmit={submit}><label>公司名称 <span>*</span><input required minLength={2} maxLength={120} value={company} onChange={e => setCompany(e.target.value)} placeholder="例如：Apple Inc." /></label><div className="form-row"><label>股票代码 <small>可选</small><input maxLength={12} value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} placeholder="AAPL" /></label><label>资料截止日期<input required type="date" value={asOf} max={today} onChange={e => setAsOf(e.target.value)} /></label></div><label>完整财年范围<select value={periods} onChange={e => setPeriods(Number(e.target.value))}>{[1,2,3,4,5].map(n => <option key={n} value={n}>最近 {n} 年</option>)}</select></label><div className="form-note">首版面向美国非金融上市公司。需要有效的 SEC 身份标识、Google 搜索与 LLM 配置。</div>{error && <div className="error-box">{error}</div>}<button className="primary-button" disabled={busy}>{busy ? '正在创建…' : '启动 Agent 研究'} <span>→</span></button></form></section>
      <section className="card recent-card"><div className="card-heading"><div><span className="section-number">02 / 工作记录</span><h2>最近任务</h2></div><span className="count">{runs.length} 条</span></div>{runs.length ? <div className="run-list">{runs.slice(0, 7).map(run => <button key={run.id} onClick={() => navigate(`/runs/${run.id}`)} className="run-row"><div className="run-avatar">{(run.request.ticker || run.request.company_name).slice(0, 1).toUpperCase()}</div><div><strong>{run.request.company_name}</strong><small>{dateTime(run.created_at)} · {run.request.ticker || '未指定代码'}</small></div><Status status={run.status} /></button>)}</div> : <div className="empty-state"><div className="empty-icon">◌</div><strong>尚无研究任务</strong><p>创建第一个任务后，进度和报告会出现在这里。</p></div>}</section></div>
    <div className="footnote">ANALYST WORKSPACE · 公开资料研究辅助工具，结论需人工复核。</div>
  </div>
}

function Status({ status }: { status: RunStatus }) { return <span className={`status status-${status}`}><span className="status-dot" />{statusNames[status]}</span> }

function useRun(id: string) {
  const [run, setRun] = useState<Run | null>(null)
  const [artifacts, setArtifacts] = useState<Artifacts>({})
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)
  useEffect(() => { let stopped = false; let timer: ReturnType<typeof setTimeout>; let delay = 2000; async function refresh() { try { const next = await api.get(id); if (stopped) return; setRun(next); setError(''); api.artifacts(id).then(v => { if (!stopped) setArtifacts(v) }).catch(() => {}); delay = 2000; if (!terminal.has(next.status) && next.status !== 'needs_input') timer = setTimeout(refresh, delay) } catch (e) { if (!stopped) { setError((e as Error).message); delay = Math.min(delay * 2, 30000); timer = setTimeout(refresh, delay) } } } refresh(); return () => { stopped = true; clearTimeout(timer) } }, [id, version])
  return { run, artifacts, error, reload: () => setVersion(v => v + 1) }
}

function RunPage({ id }: { id: string }) {
  const { run, artifacts, error, reload } = useRun(id)
  const [actionError, setActionError] = useState('')
  async function select(cik: number) { setActionError(''); try { await api.resolve(id, cik); reload() } catch (e) { setActionError((e as Error).message) } }
  async function retry() { setActionError(''); try { await api.retry(id); reload() } catch (e) { setActionError((e as Error).message) } }
  if (!run) return <div className="content"><div className="loading">{error || '正在读取任务…'}</div></div>
  const sources = artifacts['01_sources.json'] || []
  const metrics = artifacts['02_metrics.json'] || []
  return <div className="content detail"><button className="back-link" onClick={() => navigate('/')}>← 返回工作台</button><div className="page-title"><div><div className="eyebrow">RESEARCH RUN / {id.slice(0, 8).toUpperCase()}</div><h1>{run.request.company_name}</h1><p>{run.request.ticker || '公司身份待确认'} · 资料截止 {run.request.as_of_date} · 创建于 {dateTime(run.created_at)}</p></div><Status status={run.status} /></div>
    {((run.error && run.status !== 'needs_review') || error || actionError) && <div className="error-box">{actionError || error || run.error}</div>}
    {artifacts['revision.json'] && <div className="review-banner">这是重新分析的版本。<button className="text-button" onClick={() => navigate(`/runs/${artifacts['revision.json']!.parent_run_id}`)}>查看上一版本 →</button></div>}
    <ReviewPanel id={id} run={run} artifacts={artifacts} />
    {run.status === 'needs_input' && <section className="card selection"><h2>请选择正确的公司</h2><p>SEC 找到多个候选，请确认后继续。</p><div className="candidates">{run.candidates.map(c => <button key={c.cik} onClick={() => select(c.cik)}><strong>{c.legal_name}</strong><span>{c.ticker} · CIK {c.cik} →</span></button>)}</div></section>}
    <div className="detail-grid"><section className="card timeline-card"><div className="card-heading"><div><span className="section-number">WORKFLOW</span><h2>研究工作流</h2></div><span className="count">5 个阶段</span></div><div className="timeline">{run.stages.map((stage, index) => <div className={`timeline-item ${stage.status}`} key={stage.name}><div className="timeline-rail"><span className="timeline-circle">{stage.status === 'succeeded' ? '✓' : String(index + 1).padStart(2, '0')}</span></div><div className="timeline-body"><div className="timeline-head"><strong>{stageNames[stage.name]}</strong><Status status={stage.status} /></div><p>{stage.name === 'identity' ? '确认 SEC CIK 与公司法定名称' : stage.name === 'research' ? '检索公开信息并建立来源索引' : stage.name === 'analysis' ? '提取 XBRL 事实并计算财务指标' : stage.name === 'writing' ? '生成结构化投研初稿' : '核对数字、引用与报告章节'}</p><div className="timeline-meta">尝试 {stage.attempts} 次 · {stage.finished_at ? `完成 ${dateTime(stage.finished_at)}` : stage.started_at ? `开始 ${dateTime(stage.started_at)}` : '待执行'}</div>{stage.error && <div className="stage-error">{stage.error}</div>}{run.events.filter(event => event.stage === stage.name).length > 0 && <details><summary>查看工具调用 <span>{run.events.filter(event => event.stage === stage.name).length} 次</span></summary><div className="artifact-list">{run.events.filter(event => event.stage === stage.name).map((event, i) => <div key={`${event.tool}-${i}`}><span>{event.status === 'succeeded' ? '✓' : '!'}</span> {event.tool} · {event.latency_ms}ms{event.error_code ? ` · ${event.error_code}` : ''}</div>)}</div></details>}{stage.artifact_ids.length > 0 && <details><summary>查看中间产出 <span>{stage.artifact_ids.length} 份</span></summary><div className="artifact-list">{stage.artifact_ids.map(name => <div key={name}><span>▤</span> {name}{Boolean(artifacts[name]) && <pre className="artifact-preview">{JSON.stringify(artifacts[name], null, 2).slice(0, 1800)}</pre>}</div>)}</div></details>}</div></div>)}</div></section>
      <div className="detail-side"><section className="card insight-card"><div className="section-number">RUN OVERVIEW</div><h2>任务概览</h2><div className="insight-row"><span>当前阶段</span><strong>{stageNames[run.stage] || run.stage}</strong></div><div className="insight-row"><span>可追溯来源</span><strong>{sources.length} 条</strong></div><div className="insight-row"><span>财务指标</span><strong>{metrics.length} 项</strong></div><div className="insight-row"><span>自动校验</span><strong>{artifacts['04_validation.json']?.passed ? '通过' : artifacts['04_validation.json'] ? '需复核' : '待执行'}</strong></div>{run.status === 'failed' && <button className="secondary-button" onClick={retry}>从失败阶段重试 ↗</button>}{(run.status === 'succeeded' || run.status === 'needs_review') && <button className="primary-button" onClick={() => navigate(`/runs/${id}/report`)}>查看完整报告 <span>→</span></button>}</section>
        <section className="card mini-card"><div className="section-number">EVIDENCE</div><h2>来源概览</h2>{sources.slice(0, 5).map(s => <a href={s.url} key={s.source_id} target="_blank" rel="noreferrer" className="source-mini"><span>↗</span><div><strong>{s.title}</strong><small>{s.publisher} · {s.published_at || '检索来源'}</small></div></a>)}{!sources.length && <p className="muted">检索完成后显示来源。</p>}</section></div></div>
  </div>
}

function reviewIssues(artifacts: Artifacts): Issue[] {
  const validation = artifacts['04_validation.json']
  const issues: Issue[] = [...(validation?.issues || [])]
  // Historical reports only contain generic errors; show their original detail too.
  if (!validation?.issues) {
    for (const [name, stage] of [['01_research.json', 'research'], ['02_analysis.json', 'analysis']] as const) {
      for (const message of artifacts[name]?.gaps || []) issues.push({ stage, severity: 'blocking', message, action: '补充可追溯的原文证据，或撤回相关结论后重新分析' })
      for (const message of artifacts[name]?.limitations || []) issues.push({ stage, severity: 'warning', message, action: '保留为分析局限' })
    }
  }
  for (const message of validation?.errors || []) {
    if (!['研究资料存在未解决缺口', '财报分析存在未解决缺口'].includes(message) && !issues.some(issue => issue.message === message)) issues.push({ stage: 'validation', severity: 'blocking', message, action: '检查原始来源和指标口径后重新分析' })
  }
  return issues
}

function ReviewPanel({ id, run, artifacts }: { id: string; run: Run; artifacts: Artifacts }) {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<Supplement[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [key, setKey] = useState(() => crypto.randomUUID())
  const issues = reviewIssues(artifacts)
  if (!terminal.has(run.status)) return null
  const blocking = issues.filter(i => i.severity === 'blocking')
  const warnings = issues.filter(i => i.severity === 'warning')
  function edit(index: number, field: keyof Supplement, value: string) { setKey(crypto.randomUUID()); setItems(previous => previous.map((item, i) => i === index ? { ...item, [field]: value } : item)) }
  async function reanalyze(mode: 'complete_evidence' | 'remove_unsupported', useSupplements = false) {
    setBusy(true); setError('')
    try { const result = await api.reanalyze(id, useSupplements ? items : [], `${key}:${mode}:${useSupplements}`, mode); navigate(`/runs/${result.run_id}`) }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  function submit(event: React.FormEvent) {
    event.preventDefault(); void reanalyze('complete_evidence', true)
  }
  const remaining = Math.max(0, 5 - (artifacts['revision.json']?.supplements.length || 0))
  return <section className="card review-panel">
    <div className="card-heading"><div><span className="section-number">资料复核与补充</span><h2>{run.status === 'needs_review' ? '初稿已生成，核心证据仍需补齐' : '复核资料与重新分析'}</h2></div><span className="count">{blocking.length} 项待处理 · {warnings.length} 项局限</span></div>
    <p className="review-help">“待补齐”会阻止自动校验通过；“分析局限”会随报告披露。补充资料后将创建新版本，重新检索、分析和校验，原报告保留。</p>
    {blocking.length > 0 && <div className="gap-list"><h3>待补齐的核心证据</h3>{blocking.map((issue, i) => <div className="gap-item" key={i}><strong>{stageNames[issue.stage]} · 待补齐</strong><p>{issue.message}</p><small>{issue.action}</small></div>)}</div>}
    {warnings.length > 0 && <details className="limitations"><summary>查看 {warnings.length} 项分析局限（不阻断通过）</summary>{warnings.map((issue, i) => <p key={i}>{issue.message}</p>)}</details>}
    <div className="review-actions"><button className="primary-button" disabled={busy} onClick={() => reanalyze('complete_evidence')}>{busy ? '正在创建新版本…' : '自动补证据并重新分析'}</button><button className="secondary-button" disabled={busy} onClick={() => reanalyze('remove_unsupported')}>撤回无依据结论并重新分析</button></div>
    <p className="review-help">自动补证据会重新获取财报、检索完整正文并复核结论。撤回模式会纠正或删除无依据的结论，核心业务、风险和必需财务指标缺失仍需补齐。指标缺失可能来自数据标签或期间解析，撤回结论无法修复这类问题，也不保证通过校验。两种操作均调用模型并保留旧版本。</p>
    {error && <div className="error-box" role="alert">{error}</div>}
    {!!artifacts['01_research.json']?.evidence?.length && <details className="limitations"><summary>查看结论与原文证据</summary>{artifacts['01_research.json']!.evidence!.map((e, i) => <div key={i}><strong>{e.claim}</strong><p>{e.verdict === 'supported' ? '复核支持' : '待核实'} · {e.source_id}</p><blockquote>{e.quote}</blockquote><p>{e.explanation}</p></div>)}</details>}
    <button className="secondary-button" disabled={busy} onClick={() => setOpen(!open)}>{open ? '收起补充资料' : '补充资料 / 重新分析 →'}</button>
    {open && <form onSubmit={submit} className="supplement-form"><p className="review-help">可粘贴年报、季报中的相关原文，并填写来源链接与发布日期。摘录会标明“用户补充、待核验”，财务数值仍由 SEC/XBRL 校验。不添加资料也可以重新检索。</p>
      {items.map((item, index) => <fieldset key={index} disabled={busy}><legend>补充资料 {index + 1}</legend><label>资料标题<input required minLength={2} maxLength={200} value={item.title} onChange={e => edit(index, 'title', e.target.value)} /></label><div className="form-row"><label>原文链接<input required type="url" value={item.url} onChange={e => edit(index, 'url', e.target.value)} placeholder="https://…" /></label><label>发布日期<input required type="date" max={run.request.as_of_date} value={item.published_at} onChange={e => edit(index, 'published_at', e.target.value)} /></label></div><label>相关原文摘录<textarea required minLength={20} maxLength={30000} rows={7} value={item.content} onChange={e => edit(index, 'content', e.target.value)} /></label><button type="button" className="text-button" onClick={() => { setItems(items.filter((_, i) => i !== index)); setKey(crypto.randomUUID()) }}>移除此资料</button></fieldset>)}
      <div className="review-actions"><button type="button" className="secondary-button" disabled={busy || items.length >= remaining} onClick={() => { setItems([...items, { title: '', url: '', published_at: '', content: '' }]); setKey(crypto.randomUUID()) }}>＋ 添加资料（最多保留五份）</button><button className="primary-button" disabled={busy}>{busy ? '正在创建新版本…' : '重新检索并分析 →'}</button></div>
    </form>}
  </section>
}

function ReportPage({ id }: { id: string }) {
  const { run, artifacts, error } = useRun(id)
  const [report, setReport] = useState('')
  useEffect(() => { api.report(id).then(setReport).catch(() => setReport('')) }, [id, run?.status])
  const sources: Source[] = artifacts['01_sources.json'] || []
  const metrics: Metric[] = artifacts['02_metrics.json'] || []
  return <div className="content report"><button className="back-link" onClick={() => navigate(`/runs/${id}`)}>← 返回任务进度</button><div className="page-title"><div><div className="eyebrow">RESEARCH OUTPUT / {id.slice(0, 8).toUpperCase()}</div><h1>投研报告</h1><p>{run?.request.company_name || '正在加载'} · 资料截止 {run?.request.as_of_date || '—'}</p></div>{run && <Status status={run.status} />}</div>
    {run?.status === 'needs_review' && <div className="review-banner">◈ 这份报告已生成初稿，仍有核心证据待补齐。返回任务进度可查看具体缺口、补充资料并重新分析。</div>}
    {error && <div className="error-box">{error}</div>}
    {!report ? <section className="card empty-report"><div className="empty-icon">▤</div><h2>报告尚未生成</h2><p>任务完成撰写与校验后，报告会显示在这里。</p><button className="secondary-button" onClick={() => navigate(`/runs/${id}`)}>查看任务进度</button></section> : <><FinancialTrends metrics={metrics} sources={sources} /><div className="report-grid"><article className="card report-document"><div className="document-toolbar"><span>MARKDOWN REPORT · 自动生成初稿</span><a className="download-button" href={api.downloadUrl(id)}>↓ 下载 Markdown</a></div><div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ href, children }) => <a href={href} target={href?.startsWith('http') ? '_blank' : undefined} rel={href?.startsWith('http') ? 'noreferrer' : undefined}>{children}</a> }}>{report}</ReactMarkdown></div></article><aside className="report-aside"><section className="card"><div className="section-number">KEY METRICS</div><h2>关键指标</h2>{metrics.filter(m => m.status === 'verified').slice(0, 6).map(m => <div className="metric-row" key={m.metric_id}><span>{m.name}<small>{m.period}</small></span><strong>{formatMetric(m)}</strong></div>)}{!metrics.length && <p className="muted">暂无指标</p>}</section><section className="card"><div className="section-number">SOURCE INDEX</div><h2>原始来源</h2>{sources.map(s => <a className="source-mini" id={s.source_id} href={s.url} target="_blank" rel="noreferrer" key={s.source_id}><span>↗</span><div><strong>{s.title}</strong><small>{s.publisher}</small></div></a>)}</section></aside></div></>}
  </div>
}

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
