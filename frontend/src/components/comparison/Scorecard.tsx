import { usePipelineStore } from '../../hooks/usePipelineStore'

function fmtMs(ms: number): string {
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`
  if (ms >= 1_000)  return `${(ms / 1_000).toFixed(2)}s`
  return `${ms.toFixed(0)}ms`
}

function fmtTok(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}k`
  return n.toLocaleString()
}

function fmtCost(usd: number): string {
  return `$${(usd * 100).toFixed(4)}¢`
}

type Better = 'A' | 'B' | null
function pickBetter(a: number, b: number, lowerWins: boolean): Better {
  if (a === b)               return null
  if (lowerWins)             return a < b ? 'A' : 'B'
  return a > b ? 'A' : 'B'
}

function MetricCell({
  label, aRaw, bRaw, aFmt, bFmt, lowerWins,
}: {
  label: string
  aRaw: number
  bRaw: number
  aFmt: string
  bFmt: string
  lowerWins: boolean
}) {
  const better = pickBetter(aRaw, bRaw, lowerWins)
  const aWin = better === 'A'
  const bWin = better === 'B'
  return (
    <div className="flex-1 px-3 py-2 border-r last:border-r-0 border-[var(--color-border)]">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">{label}</div>
      <div className="flex items-center justify-between text-xs font-mono">
        <span className={`text-indigo-${aWin ? '300' : '500'}`}>A</span>
        <span className={`font-semibold ${aWin ? 'text-indigo-300' : 'text-slate-400'}`}>
          {aFmt}{aWin && <span className="ml-1 text-emerald-400">◀</span>}
        </span>
      </div>
      <div className="flex items-center justify-between text-xs font-mono mt-0.5">
        <span className={`text-emerald-${bWin ? '300' : '500'}`}>B</span>
        <span className={`font-semibold ${bWin ? 'text-emerald-300' : 'text-slate-400'}`}>
          {bFmt}{bWin && <span className="ml-1 text-emerald-400">◀</span>}
        </span>
      </div>
    </div>
  )
}

export function Scorecard() {
  const { customStages, doclingStages } = usePipelineStore()

  const sum = (arr: typeof customStages, fn: (s: typeof customStages[number]) => number) =>
    arr.reduce((acc, s) => acc + (fn(s) || 0), 0)

  const aLat = sum(customStages,  (s) => s.duration_ms ?? 0)
  const bLat = sum(doclingStages, (s) => s.duration_ms ?? 0)

  const aTok =
    sum(customStages,  (s) => (s.payload?.llm_input_tokens  as number) ?? 0) +
    sum(customStages,  (s) => (s.payload?.llm_output_tokens as number) ?? 0)
  const bTok =
    sum(doclingStages, (s) => (s.payload?.llm_input_tokens  as number) ?? 0) +
    sum(doclingStages, (s) => (s.payload?.llm_output_tokens as number) ?? 0)

  const aCost = sum(customStages,  (s) => (s.payload?.llm_cost_usd as number) ?? 0)
  const bCost = sum(doclingStages, (s) => (s.payload?.llm_cost_usd as number) ?? 0)

  const anyData =
    customStages.some((s) => s.status === 'completed') ||
    doclingStages.some((s) => s.status === 'completed')
  if (!anyData) return null

  return (
    <div className="border border-[var(--color-border)] rounded-xl bg-[var(--color-surface)] overflow-hidden flex-shrink-0">
      {/* Header */}
      <div className="px-3 py-1.5 border-b border-[var(--color-border)] flex items-center justify-between">
        <span className="text-xs font-semibold text-white">A vs B Scorecard</span>
        <span className="text-[10px] text-slate-500">◀ better</span>
      </div>

      {/* Headline metrics */}
      <div className="flex divide-x divide-[var(--color-border)]">
        <MetricCell label="Latency"    aRaw={aLat}  bRaw={bLat}  aFmt={fmtMs(aLat)}    bFmt={fmtMs(bLat)}    lowerWins={true}  />
        <MetricCell label="Tokens"     aRaw={aTok}  bRaw={bTok}  aFmt={fmtTok(aTok)}   bFmt={fmtTok(bTok)}   lowerWins={true}  />
        <MetricCell label="Cost"       aRaw={aCost} bRaw={bCost} aFmt={fmtCost(aCost)} bFmt={fmtCost(bCost)} lowerWins={true}  />
      </div>

      {/* Per-step latency */}
      <div className="border-t border-[var(--color-border)] grid grid-cols-2 divide-x divide-[var(--color-border)]">
        <StepLatencyColumn label="Pipeline A — Custom"  badge="A" stages={customStages}  color="indigo"  />
        <StepLatencyColumn label="Pipeline B — Docling" badge="B" stages={doclingStages} color="emerald" />
      </div>
    </div>
  )
}

function StepLatencyColumn({
  label, badge, stages, color,
}: {
  label: string
  badge: string
  stages: ReturnType<typeof usePipelineStore.getState>['customStages']
  color: 'indigo' | 'emerald'
}) {
  const completed = stages.filter((s) => s.status === 'completed' || s.duration_ms != null)
  const total = stages.reduce((acc, s) => acc + (s.duration_ms ?? 0), 0)
  const maxDur = Math.max(1, ...completed.map((s) => s.duration_ms ?? 0))
  const badgeBg = color === 'indigo' ? 'bg-indigo-600' : 'bg-emerald-700'
  const barColor = color === 'indigo' ? 'bg-indigo-500/40' : 'bg-emerald-500/40'
  const textColor = color === 'indigo' ? 'text-indigo-300' : 'text-emerald-300'

  return (
    <div className="min-w-0">
      <div className="px-3 py-1.5 flex items-center gap-2 border-b border-[var(--color-border)]">
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold text-white ${badgeBg}`}>{badge}</span>
        <span className="text-xs text-slate-400 flex-1 truncate">{label}</span>
        <span className={`text-xs font-mono font-semibold ${textColor}`}>{fmtMs(total)}</span>
      </div>
      <div className="max-h-40 overflow-y-auto">
        {completed.length === 0 ? (
          <div className="px-3 py-2 text-[11px] text-slate-600">No completed stages yet</div>
        ) : (
          completed.map((s) => {
            const dur = s.duration_ms ?? 0
            const widthPct = Math.max(2, Math.round((dur / maxDur) * 100))
            return (
              <div key={s.id} className="px-3 py-0.5 flex items-center gap-2 text-[11px] font-mono">
                <span className="text-slate-600 w-4 text-right">{s.id}.</span>
                <span className="text-slate-400 flex-1 truncate">{s.name}</span>
                <div className="w-16 h-1.5 bg-slate-800 rounded overflow-hidden">
                  <div className={`h-full ${barColor}`} style={{ width: `${widthPct}%` }} />
                </div>
                <span className={`${textColor} w-14 text-right`}>{fmtMs(dur)}</span>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
