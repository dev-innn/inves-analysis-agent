import type { Artifacts, Run, Supplement } from './types'

const base = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...options?.headers } })
  if (!response.ok) {
    let message = `请求失败 (${response.status})`
    try { const body = await response.json(); message = body.message ?? body.detail?.message ?? message } catch { /* network body is not JSON */ }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  list: () => request<Run[]>('/runs?limit=20'),
  get: (id: string) => request<Run>(`/runs/${id}`),
  artifacts: (id: string) => request<Artifacts>(`/runs/${id}/artifacts`),
  create: (input: { company_name: string; ticker?: string; as_of_date: string; report_periods: number }) => request<{ run_id: string }>('/runs', { method: 'POST', body: JSON.stringify(input) }),
  resolve: (id: string, cik: number) => request(`/runs/${id}/resolve-company`, { method: 'POST', body: JSON.stringify({ cik }) }),
  retry: (id: string) => request(`/runs/${id}/retry`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } }),
  reanalyze: (id: string, supplements: Supplement[], key: string, mode: 'complete_evidence' | 'remove_unsupported' = 'complete_evidence') => request<{ run_id: string }>(`/runs/${id}/reanalyze`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify({ supplements, mode }) }),
  report: async (id: string) => {
    const response = await fetch(`${base}/runs/${id}/report`)
    if (!response.ok) throw new Error('报告尚未生成')
    return response.text()
  },
  downloadUrl: (id: string) => `${base}/runs/${id}/report?download=1`,
}
