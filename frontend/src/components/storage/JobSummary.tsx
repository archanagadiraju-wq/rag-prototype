import { useEffect, useState } from 'react'

interface AnthropicTotals {
  input_tokens: number
  output_tokens: number
  cache_create_tokens: number
  cache_read_tokens: number
  cost_usd: number
  no_cache_baseline_usd: number
  saved_usd: number
  saved_pct: number
}

interface OpenAITotals {
  embedding_tokens: number
  cost_usd: number
}

interface StageRow {
  stage_id: number
  name: string
  duration_ms: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
}

interface JobSummaryData {
  job_id: string
  pipeline: string | null
  filename: string | null
  status: string
  wall_time_s: number
  iterations: number | null
  anthropic: AnthropicTotals
  openai: OpenAITotals
  total_cost_usd: number
  total_tokens: number
  stages: StageRow[]
}


function fmtCost(usd: number): string {
  if (usd >= 0.01) return `$${usd.toFixed(4)}`
  return `$${(usd * 100).toFixed(4)}¢`
}

function fmtTok(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return n.toLocaleString()
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}


export function JobSummary({ jobId }: { jobId: string | null }) {
  const [data, setData] = useState<JobSummaryData | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    if (!jobId) return
    setError(null)
    try {
      const r = await fetch(`/api/jobs/${jobId}/summary`)
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setError(d.detail || `${r.status} ${r.statusText}`)
        setData(null)
        return
      }
      setData(await r.json())
    } catch (exc: unknown) {
      setError(exc instanceof Error ? exc.message : 'request failed')
    }
  }

  useEffect(() => { void refresh() }, [jobId])

  if (!jobId) return null
  if (error) return null  // silent — JobSummary is a "nice to have", not required
  if (!data) return null

  return (
    <div className="space-y-3">
      {/* Hero numbers — wall time, total cost, total tokens */}
      <div className="rounded-xl border border-indigo-500/30 bg-gradient-to-br from-indigo-900/20 to-slate-900/40 p-4">
        <div className="flex items-center justify-between mb-3">
          <p className="text-[10px] uppercase tracking-wider text-indigo-300 font-semibold">
            Job summary
          </p>
          <button onClick={refresh} className="text-[10px] text-indigo-400 hover:text-indigo-300 underline-offset-2 hover:underline">
            refresh
          </button>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <p className="text-[10px] text-slate-500 uppercase">Wall time</p>
            <p className="text-2xl font-bold text-white tabular-nums">
              {data.wall_time_s < 60 ? `${data.wall_time_s.toFixed(1)}s` : `${(data.wall_time_s / 60).toFixed(1)}m`}
            </p>
            {data.iterations != null && (
              <p className="text-[10px] text-slate-500">{data.iterations} agent turn{data.iterations !== 1 ? 's' : ''}</p>
            )}
          </div>
          <div>
            <p className="text-[10px] text-slate-500 uppercase">Total cost</p>
            <p className="text-2xl font-bold text-emerald-300 tabular-nums">{fmtCost(data.total_cost_usd)}</p>
            {data.anthropic.saved_pct > 0 && (
              <p className="text-[10px] text-emerald-500">
                saved {fmtCost(data.anthropic.saved_usd)} ({data.anthropic.saved_pct.toFixed(1)}%) via cache
              </p>
            )}
          </div>
          <div>
            <p className="text-[10px] text-slate-500 uppercase">Total tokens</p>
            <p className="text-2xl font-bold text-white tabular-nums">{fmtTok(data.total_tokens)}</p>
            <p className="text-[10px] text-slate-500">
              {fmtTok(data.anthropic.input_tokens + data.anthropic.output_tokens)} Anthropic ·{' '}
              {fmtTok(data.openai.embedding_tokens)} OpenAI
            </p>
          </div>
        </div>
      </div>

      {/* Cost breakdown by provider */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden">
        <div className="px-3 py-2 border-b border-[var(--color-border)] text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
          Cost breakdown
        </div>
        <div className="divide-y divide-[var(--color-border)] text-xs">
          {/* Anthropic */}
          <div className="px-3 py-2">
            <div className="flex items-center justify-between">
              <span className="text-amber-300 font-medium">Anthropic (Claude haiku)</span>
              <span className="font-mono font-semibold text-amber-300">{fmtCost(data.anthropic.cost_usd)}</span>
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 mt-1.5 text-[10px] font-mono">
              <div className="flex justify-between text-slate-500">
                <span>input (uncached)</span><span>{fmtTok(data.anthropic.input_tokens)} tok · {fmtCost(data.anthropic.input_tokens * 0.80 / 1e6)}</span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>output</span><span>{fmtTok(data.anthropic.output_tokens)} tok · {fmtCost(data.anthropic.output_tokens * 4.00 / 1e6)}</span>
              </div>
              <div className="flex justify-between text-emerald-500/80">
                <span>cache read (90% off)</span><span>{fmtTok(data.anthropic.cache_read_tokens)} tok · {fmtCost(data.anthropic.cache_read_tokens * 0.08 / 1e6)}</span>
              </div>
              <div className="flex justify-between text-indigo-500/80">
                <span>cache write (1.25×)</span><span>{fmtTok(data.anthropic.cache_create_tokens)} tok · {fmtCost(data.anthropic.cache_create_tokens * 1.00 / 1e6)}</span>
              </div>
            </div>
            {data.anthropic.saved_pct > 0 && (
              <p className="mt-1.5 text-[10px] text-emerald-500/80 italic">
                vs no-cache baseline {fmtCost(data.anthropic.no_cache_baseline_usd)} — saved {data.anthropic.saved_pct.toFixed(1)}%
              </p>
            )}
          </div>

          {/* OpenAI */}
          <div className="px-3 py-2">
            <div className="flex items-center justify-between">
              <span className="text-cyan-300 font-medium">OpenAI (text-embedding-3-large)</span>
              <span className="font-mono font-semibold text-cyan-300">{fmtCost(data.openai.cost_usd)}</span>
            </div>
            <div className="mt-1 text-[10px] font-mono text-slate-500 flex justify-between">
              <span>embedding tokens</span><span>{fmtTok(data.openai.embedding_tokens)} · {fmtCost(data.openai.embedding_tokens * 0.13 / 1e6)}</span>
            </div>
          </div>

          {/* Grand total */}
          <div className="px-3 py-2 bg-slate-800/40">
            <div className="flex items-center justify-between">
              <span className="text-white font-semibold">TOTAL</span>
              <span className="font-mono font-bold text-white">{fmtCost(data.total_cost_usd)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Per-stage table */}
      {data.stages.length > 0 && (
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden">
          <div className="px-3 py-2 border-b border-[var(--color-border)] text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
            Per-stage breakdown
          </div>
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-slate-500 border-b border-[var(--color-border)]">
                <th className="text-left px-3 py-1.5 font-medium">#</th>
                <th className="text-left px-2 py-1.5 font-medium">stage</th>
                <th className="text-right px-2 py-1.5 font-medium">time</th>
                <th className="text-right px-2 py-1.5 font-medium">in</th>
                <th className="text-right px-2 py-1.5 font-medium">out</th>
                <th className="text-right px-3 py-1.5 font-medium">cost</th>
              </tr>
            </thead>
            <tbody>
              {data.stages.map((s) => (
                <tr key={`${s.stage_id}_${s.name}`} className="border-b border-[var(--color-border)] last:border-b-0">
                  <td className="px-3 py-1 text-slate-600 font-mono">{s.stage_id}</td>
                  <td className="px-2 py-1 text-slate-300 font-mono truncate">{s.name}</td>
                  <td className="px-2 py-1 text-slate-400 font-mono text-right">{fmtMs(s.duration_ms)}</td>
                  <td className="px-2 py-1 text-slate-400 font-mono text-right">{fmtTok(s.input_tokens)}</td>
                  <td className="px-2 py-1 text-slate-400 font-mono text-right">{fmtTok(s.output_tokens)}</td>
                  <td className="px-3 py-1 text-emerald-400 font-mono text-right">{fmtCost(s.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
