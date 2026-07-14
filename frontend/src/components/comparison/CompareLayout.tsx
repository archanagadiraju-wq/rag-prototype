import { usePipelineStore } from '../../hooks/usePipelineStore'
import type { StageState } from '../../hooks/usePipelineStore'
import { StageCard } from '../pipeline/StageCard'
import { LiveFeed } from '../pipeline/LiveFeed'
import { RichViz } from '../pipeline/StageDetail'
import { Scorecard } from './Scorecard'

function normalize(name: string): string {
  return name.toLowerCase().replace(/[-_\s]+/g, '').trim()
}

/**
 * Match a stage on the *other* pipeline to the one selected on this side.
 * Tries name match first (so "Embedding" pairs with "Embedding" even when IDs differ),
 * falls back to stage_id when names don't overlap.
 */
function matchedOther(
  thisStage: StageState | undefined,
  otherStages: StageState[],
): StageState | undefined {
  if (!thisStage) return undefined
  const target = normalize(thisStage.name)
  const exact = otherStages.find((s) => normalize(s.name) === target)
  if (exact) return exact
  const fuzzy = otherStages.find(
    (s) => normalize(s.name).includes(target) || target.includes(normalize(s.name)),
  )
  if (fuzzy) return fuzzy
  return otherStages.find((s) => s.id === thisStage.id)
}

function PipelineColumn({
  label,
  pipeline,
  badge,
}: {
  label: string
  pipeline: 'custom' | 'docling'
  badge: string
}) {
  const { customStages, doclingStages, selectedStage, selectedPipeline, setSelectedStage } =
    usePipelineStore()
  const stages = pipeline === 'custom' ? customStages : doclingStages
  const completedCount = stages.filter((s) => s.status === 'completed').length
  const totalDuration = stages.reduce((sum, s) => sum + (s.duration_ms ?? 0), 0)

  return (
    <div className="flex-1 flex flex-col gap-2 min-w-0">
      <div className="flex items-center justify-between px-3 py-2 rounded-xl bg-[var(--color-surface)] border border-[var(--color-border)] sticky top-0 z-10">
        <div className="flex items-center gap-2">
          <span
            className={`px-2 py-0.5 rounded text-xs font-bold ${
              pipeline === 'custom' ? 'bg-indigo-600 text-white' : 'bg-emerald-700 text-white'
            }`}
          >
            {badge}
          </span>
          <span className="text-sm font-semibold text-white">{label}</span>
        </div>
        <div className="text-xs text-slate-500">
          {completedCount}/{stages.length} stages
          {totalDuration > 0 && <span className="ml-2">{totalDuration.toFixed(0)}ms</span>}
        </div>
      </div>

      <div className="space-y-1.5">
        {stages.map((s) => {
          const isSelected = selectedStage === s.id && selectedPipeline === pipeline
          return (
            <div
              key={s.id}
              onClick={() => setSelectedStage(isSelected ? null : s.id, pipeline)}
              className="cursor-pointer"
            >
              <StageCard stage={s} overrideSelected={isSelected} />
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function CompareLayout() {
  const { customStages, doclingStages, selectedStage, selectedPipeline } = usePipelineStore()

  // Which stage was clicked, on which side
  const clickedStages = selectedPipeline === 'docling' ? doclingStages : customStages
  const clickedStage = clickedStages.find((s) => s.id === selectedStage)

  // Build the matched pair: whichever side was clicked is "this", find the corresponding on "other"
  let aStage: StageState | undefined
  let bStage: StageState | undefined
  if (clickedStage) {
    if (selectedPipeline === 'custom') {
      aStage = clickedStage
      bStage = matchedOther(clickedStage, doclingStages)
    } else {
      bStage = clickedStage
      aStage = matchedOther(clickedStage, customStages)
    }
  }

  const hasSelection = !!clickedStage

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="flex flex-col gap-3 pb-3">
        <Scorecard />

        {/* Two pipeline columns, naturally tall — page scroll handles overflow */}
        <div className="flex gap-3 min-w-0">
          <PipelineColumn label="Custom Pipeline" pipeline="custom" badge="A" />
          <div className="w-px bg-[var(--color-border)] flex-shrink-0" />
          <PipelineColumn label="Docling Pipeline" pipeline="docling" badge="B" />
        </div>

        {/* Parallel stage detail panel — only when a stage is selected */}
        {hasSelection && (
          <ParallelStageDetail
            aStage={aStage}
            bStage={bStage}
            clickedSide={selectedPipeline === 'docling' ? 'B' : 'A'}
          />
        )}

        <LiveFeed />
      </div>
    </div>
  )
}

function ParallelStageDetail({
  aStage,
  bStage,
  clickedSide,
}: {
  aStage: StageState | undefined
  bStage: StageState | undefined
  clickedSide: 'A' | 'B'
}) {
  const title = (aStage ?? bStage)?.name ?? 'Stage'

  return (
    <div className="border border-[var(--color-border)] rounded-xl bg-[var(--color-surface)] overflow-hidden">
      <div className="px-3 py-2 border-b border-[var(--color-border)] flex items-center gap-2">
        <span className="text-xs font-semibold text-white">Stage detail — A vs B</span>
        <span className="text-xs text-slate-500">· {title}</span>
        <span className="ml-auto text-[10px] text-slate-600">
          matched by name; clicked side: {clickedSide}
        </span>
      </div>

      {/* A vs B metric strip (token burn, latency, L1) for matched pair */}
      <div className="px-3 py-2 border-b border-[var(--color-border)]">
        <PairQuickCompare a={aStage} b={bStage} />
      </div>

      <div className="grid grid-cols-2 divide-x divide-[var(--color-border)]">
        <SideDetail stage={aStage} badge="A" color="indigo" />
        <SideDetail stage={bStage} badge="B" color="emerald" />
      </div>
    </div>
  )
}

function SideDetail({
  stage,
  badge,
  color,
}: {
  stage: StageState | undefined
  badge: string
  color: 'indigo' | 'emerald'
}) {
  const badgeBg = color === 'indigo' ? 'bg-indigo-600' : 'bg-emerald-700'
  const accent = color === 'indigo' ? 'text-indigo-300' : 'text-emerald-300'

  if (!stage) {
    return (
      <div className="p-3">
        <div className="flex items-center gap-2 mb-2">
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold text-white ${badgeBg}`}>
            {badge}
          </span>
          <span className="text-xs text-slate-500">No matching stage in this pipeline</span>
        </div>
        <p className="text-xs text-slate-600">
          The selected stage doesn't exist on this side (e.g. Docling collapses
          format-detect/parse/content-intel/chunk into a single unified-parse stage).
        </p>
      </div>
    )
  }

  return (
    <div className="p-3 space-y-3 min-w-0">
      <div className="flex items-center gap-2">
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold text-white ${badgeBg}`}>
          {badge}
        </span>
        <span className={`text-sm font-semibold ${accent} truncate`}>
          Stage {stage.id} — {stage.name}
        </span>
        {stage.duration_ms != null && (
          <span className="text-xs text-slate-500 ml-auto flex-shrink-0">
            {stage.duration_ms.toFixed(0)}ms
          </span>
        )}
      </div>

      {stage.status === 'completed' ? (
        <RichViz stage={stage} />
      ) : (
        <p className="text-xs text-slate-500 italic">
          Status: {stage.status}
          {stage.status === 'idle' && ' — not run yet'}
        </p>
      )}

      {stage.verification && stage.verification.l1_checks.length > 0 && (
        <div>
          <p className="text-[10px] text-slate-500 font-medium uppercase tracking-wider mb-1">
            Verification
          </p>
          <div className="space-y-1">
            {stage.verification.l1_checks.map((c, i) => (
              <div
                key={i}
                className={`flex items-start gap-2 text-[11px] px-2 py-1 rounded ${
                  c.passed
                    ? 'bg-emerald-900/20 text-emerald-300'
                    : c.severity === 'warn'
                      ? 'bg-yellow-900/20 text-yellow-300'
                      : 'bg-red-900/20 text-red-300'
                }`}
              >
                <span className="font-mono">
                  {c.passed ? '✓' : c.severity === 'warn' ? '△' : '✗'}
                </span>
                <div className="min-w-0">
                  <span className="font-medium">{c.name.replace(/_/g, ' ')}</span>
                  {c.detail && <span className="opacity-70 ml-2">{c.detail}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {stage.payload && (
        <details className="text-xs">
          <summary className="cursor-pointer text-slate-500 hover:text-slate-300">
            Raw payload
          </summary>
          <pre className="mt-1 bg-[var(--color-bg)] rounded-lg p-2 overflow-auto text-slate-300 max-h-64 border border-[var(--color-border)]">
            {JSON.stringify(stage.payload, null, 2)}
          </pre>
        </details>
      )}
    </div>
  )
}

function PairQuickCompare({ a, b }: { a: StageState | undefined; b: StageState | undefined }) {
  const rows: { label: string; a: string; b: string }[] = []

  const aDur = a?.duration_ms
  const bDur = b?.duration_ms
  if (aDur != null || bDur != null) {
    rows.push({
      label: 'Duration',
      a: aDur != null ? `${aDur.toFixed(0)}ms` : '—',
      b: bDur != null ? `${bDur.toFixed(0)}ms` : '—',
    })
  }
  if (a?.verification && b?.verification) {
    rows.push({
      label: 'L1 pass rate',
      a: `${(a.verification.l1_pass_rate * 100).toFixed(0)}%`,
      b: `${(b.verification.l1_pass_rate * 100).toFixed(0)}%`,
    })
  }
  const aIn = a?.payload?.llm_input_tokens as number | undefined
  const bIn = b?.payload?.llm_input_tokens as number | undefined
  const aOut = a?.payload?.llm_output_tokens as number | undefined
  const bOut = b?.payload?.llm_output_tokens as number | undefined
  const aCost = a?.payload?.llm_cost_usd as number | undefined
  const bCost = b?.payload?.llm_cost_usd as number | undefined
  const fmtTok = (v: number | undefined) => (v == null ? '—' : v.toLocaleString())
  const fmtCost = (v: number | undefined) => (v == null ? '—' : `$${(v * 100).toFixed(4)}¢`)
  if (aIn != null || bIn != null)
    rows.push({ label: 'LLM input', a: fmtTok(aIn), b: fmtTok(bIn) })
  if (aOut != null || bOut != null)
    rows.push({ label: 'LLM output', a: fmtTok(aOut), b: fmtTok(bOut) })
  if (aCost != null || bCost != null)
    rows.push({ label: 'LLM cost', a: fmtCost(aCost), b: fmtCost(bCost) })

  if (rows.length === 0) return null

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-slate-500">
          <th className="text-left pb-1 font-medium">Metric</th>
          <th className="text-right pb-1 text-indigo-400 font-medium">A</th>
          <th className="text-right pb-1 text-emerald-400 font-medium">B</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label} className="text-slate-300">
            <td className="py-0.5">{r.label}</td>
            <td className="text-right text-indigo-300 font-mono">{r.a}</td>
            <td className="text-right text-emerald-300 font-mono">{r.b}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
