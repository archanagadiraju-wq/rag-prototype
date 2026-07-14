import { useEffect, useState } from 'react'
import type { StageState } from '../../hooks/usePipelineStore'

interface AnswerItem {
  index: number
  question: string
  route: string
  type: string
  difficulty: string
  sql_fallback: boolean
  answer: string
  input_tokens: number
  output_tokens: number
  latency_ms: number
  confidence: number
  confidence_label: string
  sql_query?: string | null
  sql_cols?: string[] | null
  sql_rows?: unknown[][] | null
  context_chunks: number
  // Captured prompts (so the UI can render them in a popup)
  system_prompt?: string
  user_prompt?: string
  // LLM-as-judge fields (separate Claude pass evaluating the answer)
  judge_score?: number | null
  judge_verdict?: string | null
  judge_rationale?: string | null
  // legacy fields (mock / old format)
  query_type?: string
  query?: string
  label?: string
  entity_subject?: string
}

interface LLMAnswerPayload {
  answers?: AnswerItem[]
  total_input_tokens?: number
  total_output_tokens?: number
  total_tokens?: number
  total_llm_ms?: number
  total_cost_usd?: number
  model_used?: string
  use_real_embeddings?: boolean
  judge_avg_score?: number
  judge_verdict_counts?: Record<string, number>
  judge_input_tokens?: number
  judge_output_tokens?: number
}

// ── Route colour system ───────────────────────────────────────────────────────

const ROUTE_STYLE: Record<string, { badge: string; ring: string; dot: string; label: string }> = {
  vector:   { badge: 'bg-indigo-900/40 border-indigo-600/40 text-indigo-300',   ring: 'border-indigo-700/30',  dot: 'bg-indigo-400',  label: 'Vector' },
  kg:       { badge: 'bg-violet-900/40 border-violet-600/40 text-violet-300',   ring: 'border-violet-700/30',  dot: 'bg-violet-400',  label: 'Graph' },
  sql:      { badge: 'bg-amber-900/40  border-amber-600/40  text-amber-300',    ring: 'border-amber-700/30',   dot: 'bg-amber-400',   label: 'SQL' },
  'sql+vec':{ badge: 'bg-emerald-900/40 border-emerald-600/40 text-emerald-300',ring: 'border-emerald-700/30', dot: 'bg-emerald-400', label: 'SQL+Vec' },
  'vec+sql':{ badge: 'bg-emerald-900/40 border-emerald-600/40 text-emerald-300',ring: 'border-emerald-700/30', dot: 'bg-emerald-400', label: 'Hybrid' },
  hybrid:   { badge: 'bg-emerald-900/40 border-emerald-600/40 text-emerald-300',ring: 'border-emerald-700/30', dot: 'bg-emerald-400', label: 'Hybrid' },
}

function routeStyle(route: string) {
  return ROUTE_STYLE[route] ?? ROUTE_STYLE.vector
}

// ── Difficulty badge ──────────────────────────────────────────────────────────

const DIFF_STYLE: Record<string, string> = {
  easy:   'bg-slate-800/60 border-slate-600/40 text-slate-400',
  medium: 'bg-amber-900/30 border-amber-600/30 text-amber-400',
  hard:   'bg-red-900/30   border-red-600/30   text-red-400',
}

// ── LLM-as-judge helpers ──────────────────────────────────────────────────────

const JUDGE_STYLE: Record<string, { bg: string; border: string; text: string; bar: string }> = {
  correct:     { bg: 'bg-emerald-900/30', border: 'border-emerald-600/40', text: 'text-emerald-300', bar: 'bg-emerald-500' },
  partial:     { bg: 'bg-amber-900/30',   border: 'border-amber-600/40',   text: 'text-amber-300',   bar: 'bg-amber-500'   },
  unsupported: { bg: 'bg-orange-900/30',  border: 'border-orange-600/40',  text: 'text-orange-300',  bar: 'bg-orange-500'  },
  incorrect:   { bg: 'bg-red-900/30',     border: 'border-red-600/40',     text: 'text-red-300',     bar: 'bg-red-500'     },
  unknown:     { bg: 'bg-slate-800/60',   border: 'border-slate-600/40',   text: 'text-slate-400',   bar: 'bg-slate-500'   },
}

function JudgeBadge({ verdict }: { verdict: string }) {
  const s = JUDGE_STYLE[verdict] ?? JUDGE_STYLE.unknown
  return (
    <div
      className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10px] font-semibold ${s.bg} ${s.border} ${s.text}`}
      title={`LLM-as-judge verdict: ${verdict}`}
    >
      <span className="text-[9px]">⚖</span>
      {verdict}
    </div>
  )
}

function JudgeBar({ score, verdict, rationale }: { score: number; verdict: string; rationale: string }) {
  const s = JUDGE_STYLE[verdict] ?? JUDGE_STYLE.unknown
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[10px]">
        <span className="text-slate-500">⚖ LLM-as-judge</span>
        <span className={`font-semibold ${s.text}`}>
          {verdict} · {(score * 100).toFixed(0)}%
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${s.bar}`}
          style={{ width: `${Math.min(100, score * 100)}%` }}
        />
      </div>
      {rationale && (
        <p className={`text-[10px] italic ${s.text} opacity-90 leading-snug`}>
          {rationale}
        </p>
      )}
    </div>
  )
}

// ── SQL result table ──────────────────────────────────────────────────────────

function SqlResult({ cols, rows }: { cols: string[]; rows: unknown[][] }) {
  return (
    <div className="overflow-x-auto rounded border border-amber-700/30 bg-amber-950/20">
      <table className="text-[10px] w-full">
        <thead>
          <tr className="border-b border-amber-700/30">
            {cols.map((c, i) => (
              <th key={i} className="px-2 py-1 text-left text-amber-400 font-semibold whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className="border-b border-amber-900/20 last:border-0">
              {(row as unknown[]).map((cell, ci) => (
                <td key={ci} className="px-2 py-1 text-slate-300 font-mono whitespace-nowrap">
                  {String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Single answer card ────────────────────────────────────────────────────────

function AnswerCard({ item, defaultOpen }: { item: AnswerItem; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const [sqlOpen, setSqlOpen] = useState(false)
  const [promptOpen, setPromptOpen] = useState(false)

  // Support both new format (route/question) and legacy (query_type/query)
  const route   = item.route ?? item.query_type ?? 'vector'
  const question = item.question ?? item.query ?? ''
  const diff    = item.difficulty ?? 'medium'
  const rs      = routeStyle(route)
  const hasSql  = !!(item.sql_cols && item.sql_cols.length > 0 && item.sql_rows && item.sql_rows.length > 0)
  const isSqlRoute = route.includes('sql')

  return (
    <div className={`rounded-xl border overflow-hidden bg-[var(--color-bg)] ${rs.ring}`}>
      {/* Header */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full text-left px-3 py-2.5 flex items-start gap-2.5 hover:bg-slate-800/30 transition-colors"
      >
        {/* Index */}
        <span className="text-[10px] font-bold text-slate-600 tabular-nums mt-0.5 w-5 shrink-0 text-right">
          {item.index ?? ''}
        </span>
        <div className="flex-1 min-w-0 space-y-1.5">
          <div className="flex items-center gap-1.5 flex-wrap">
            {/* Route badge */}
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${rs.badge}`}>
              {rs.label}
            </span>
            {/* Difficulty */}
            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${DIFF_STYLE[diff] ?? DIFF_STYLE.medium}`}>
              {diff}
            </span>
            {/* Type chip */}
            {item.type && (
              <span className="text-[10px] text-slate-500 font-mono">{item.type}</span>
            )}
            {/* SQL fallback warning */}
            {item.sql_fallback && (
              <span className="text-[10px] text-orange-400 font-medium">⚠ no table → vector</span>
            )}
            {item.judge_score != null && item.judge_verdict && <JudgeBadge verdict={item.judge_verdict} />}
          </div>
          <p className="text-xs text-slate-400 italic leading-snug">"{question}"</p>
        </div>
        {/* Stats */}
        <div className="flex items-center gap-1.5 shrink-0 self-start mt-0.5">
          {hasSql && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/30 border border-amber-700/30 text-amber-400 whitespace-nowrap">
              SQL
            </span>
          )}
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800/60 border border-slate-700/40 text-slate-400 whitespace-nowrap">
            {(item.input_tokens + item.output_tokens).toLocaleString()} tok
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800/60 border border-slate-700/40 text-slate-400 whitespace-nowrap">
            {item.latency_ms < 1000
              ? `${item.latency_ms.toFixed(0)}ms`
              : `${(item.latency_ms / 1000).toFixed(2)}s`}
          </span>
          <span className="text-slate-600 text-xs ml-0.5">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-[var(--color-border)]">
          {/* SQL result section */}
          {isSqlRoute && hasSql && (
            <div className="px-4 py-2.5 border-b border-[var(--color-border)] space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-amber-400 uppercase tracking-wider font-semibold">
                  SQL Result ({item.sql_rows!.length} row{item.sql_rows!.length !== 1 ? 's' : ''})
                </span>
                {item.sql_query && (
                  <button
                    onClick={(e) => { e.stopPropagation(); setSqlOpen(!sqlOpen) }}
                    className="text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
                  >
                    {sqlOpen ? 'hide query ▲' : 'show query ▼'}
                  </button>
                )}
              </div>
              {sqlOpen && item.sql_query && (
                <pre className="text-[10px] font-mono text-amber-300/80 bg-amber-950/30 rounded px-2 py-1.5 overflow-x-auto whitespace-pre-wrap break-all border border-amber-800/30">
                  {item.sql_query}
                </pre>
              )}
              <SqlResult cols={item.sql_cols!} rows={item.sql_rows!} />
            </div>
          )}

          {/* Answer */}
          <div className="px-4 py-3">
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Answer</p>
              {(item.system_prompt || item.user_prompt) && (
                <button
                  onClick={(e) => { e.stopPropagation(); setPromptOpen(true) }}
                  className="text-[10px] text-indigo-400 hover:text-indigo-300 underline-offset-2 hover:underline transition-colors"
                  title="Show the system + user prompt that was sent to the model"
                >
                  view prompt ↗
                </button>
              )}
            </div>
            <p className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">{item.answer}</p>
          </div>

          {/* LLM-as-judge (primary) — independent Claude evaluation of the answer */}
          {item.judge_score != null && item.judge_verdict && (
            <div className="px-4 pb-3">
              <JudgeBar
                score={item.judge_score}
                verdict={item.judge_verdict}
                rationale={item.judge_rationale ?? ''}
              />
              <p className="mt-1 text-[9px] text-slate-600 leading-relaxed">
                A second Claude pass evaluates (question · retrieved context · answer) on a 4-tier
                rubric: correct / partial / unsupported / incorrect.
              </p>
            </div>
          )}

          {/* Token breakdown */}
          <div className="px-4 pb-3 pt-1 border-t border-[var(--color-border)] flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-1.5 text-[10px]">
              <span className="text-slate-600">Chunks:</span>
              <span className="font-medium text-slate-400">{item.context_chunks}</span>
            </div>
            {item.entity_subject && (
              <>
                <div className="text-slate-700">·</div>
                <div className="flex items-center gap-1 text-[10px]">
                  <span className="text-slate-600">entity:</span>
                  <span className="font-mono text-violet-400">{item.entity_subject}</span>
                </div>
              </>
            )}
            <div className="text-slate-700">·</div>
            <div className="flex items-center gap-1 text-[10px]">
              <span className="px-1.5 py-0.5 rounded bg-indigo-900/20 border border-indigo-700/20 text-indigo-400 font-mono">
                {item.input_tokens.toLocaleString()} in
              </span>
              <span className="text-slate-600">→</span>
              <span className="px-1.5 py-0.5 rounded bg-emerald-900/20 border border-emerald-700/20 text-emerald-400 font-mono">
                {item.output_tokens.toLocaleString()} out
              </span>
            </div>
          </div>
        </div>
      )}

      {promptOpen && (
        <PromptModal
          item={item}
          onClose={() => setPromptOpen(false)}
        />
      )}
    </div>
  )
}

function PromptModal({ item, onClose }: { item: AnswerItem; onClose: () => void }) {
  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const sys  = item.system_prompt ?? ''
  const user = item.user_prompt ?? ''

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl max-h-[85vh] flex flex-col rounded-xl bg-[var(--color-surface)] border border-[var(--color-border)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium mb-1">
              Prompt sent to model · Q{item.index}
            </p>
            <p className="text-sm text-white italic leading-snug">"{item.question ?? item.query ?? ''}"</p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-white text-xl leading-none px-2"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
          <section>
            <p className="text-[10px] text-indigo-400 uppercase tracking-wider font-semibold mb-1.5">
              system
            </p>
            <pre className="text-xs whitespace-pre-wrap font-mono text-slate-300 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-lg p-3">
              {sys || '(none — model called without a system prompt)'}
            </pre>
          </section>

          <section>
            <p className="text-[10px] text-emerald-400 uppercase tracking-wider font-semibold mb-1.5">
              user · {user.length.toLocaleString()} chars
            </p>
            <pre className="text-xs whitespace-pre-wrap font-mono text-slate-300 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-lg p-3">
              {user || '(no user prompt captured)'}
            </pre>
          </section>
        </div>

        {/* Footer */}
        <div className="px-4 py-2 border-t border-[var(--color-border)] flex items-center justify-between text-[10px] text-slate-500">
          <span>
            input {item.input_tokens.toLocaleString()} · output {item.output_tokens.toLocaleString()} · {item.latency_ms.toFixed(0)}ms
          </span>
          <span>Esc or click outside to close</span>
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function LLMAnswerViz({ stage }: { stage: StageState }) {
  const p = stage.payload as LLMAnswerPayload
  if (!p) return null

  const answers     = p.answers ?? []
  const totalIn     = p.total_input_tokens  ?? 0
  const totalOut    = p.total_output_tokens ?? 0
  const totalTokens = p.total_tokens ?? (totalIn + totalOut)
  const totalMs     = p.total_llm_ms ?? 0
  const costUsd     = p.total_cost_usd ?? 0
  const model       = p.model_used ?? '—'
  const isMock      = model === 'mock'

  // Route distribution
  const routeCounts: Record<string, number> = {}
  answers.forEach(a => {
    const r = a.route ?? a.query_type ?? 'vector'
    routeCounts[r] = (routeCounts[r] ?? 0) + 1
  })

  return (
    <div className="space-y-4">

      {/* ── Top summary banner ── */}
      <div className="rounded-xl border border-[var(--color-border)] bg-slate-900/60 overflow-hidden">
        <div className="grid grid-cols-3 divide-x divide-[var(--color-border)]">
          <div className="px-3 py-2.5 text-center">
            <p className="text-xl font-bold text-white tabular-nums">{totalTokens.toLocaleString()}</p>
            <p className="text-[10px] text-slate-500 mt-0.5">total tokens</p>
          </div>
          <div className="px-3 py-2.5 text-center">
            <p className="text-xl font-bold text-white tabular-nums">
              {totalMs < 1000 ? `${totalMs.toFixed(0)}ms` : `${(totalMs / 1000).toFixed(2)}s`}
            </p>
            <p className="text-[10px] text-slate-500 mt-0.5">LLM latency</p>
          </div>
          <div className="px-3 py-2.5 text-center">
            <p className={`text-xl font-bold tabular-nums ${isMock ? 'text-yellow-400' : 'text-white'}`}>
              {isMock ? 'mock' : costUsd > 0 ? `$${costUsd.toFixed(4)}` : '—'}
            </p>
            <p className="text-[10px] text-slate-500 mt-0.5">est. cost</p>
          </div>
        </div>

        {/* Input / output split bar */}
        {totalTokens > 0 && (
          <div className="px-3 pb-2.5 pt-1 border-t border-[var(--color-border)] space-y-1.5">
            <div className="flex h-2 rounded-full overflow-hidden bg-slate-800">
              <div className="bg-indigo-500 transition-all" style={{ width: `${(totalIn / totalTokens) * 100}%` }} />
              <div className="bg-emerald-500 transition-all" style={{ width: `${(totalOut / totalTokens) * 100}%` }} />
            </div>
            <div className="flex items-center gap-4 text-[10px]">
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-indigo-500 shrink-0" />
                <span className="text-slate-500">Input</span>
                <span className="font-mono text-slate-300">{totalIn.toLocaleString()}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
                <span className="text-slate-500">Output</span>
                <span className="font-mono text-slate-300">{totalOut.toLocaleString()}</span>
              </div>
              <div className="ml-auto flex items-center gap-1">
                <span className="text-slate-600">model:</span>
                <span className={`font-mono font-medium ${isMock ? 'text-yellow-400' : 'text-slate-300'}`}>
                  {isMock ? 'mock' : model}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── LLM-as-judge aggregate ── */}
      {p.judge_avg_score != null && p.judge_verdict_counts && Object.keys(p.judge_verdict_counts).length > 0 && (
        <div className="rounded-xl border border-[var(--color-border)] bg-slate-900/60 overflow-hidden">
          <div className="px-3 py-2 border-b border-[var(--color-border)] flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wider text-slate-500 font-medium">⚖ LLM-as-judge</span>
            <span className="text-xs font-mono font-semibold text-white">
              avg {(p.judge_avg_score * 100).toFixed(0)}%
            </span>
          </div>
          <div className="px-3 py-2 flex items-center gap-2 flex-wrap">
            {(['correct', 'partial', 'unsupported', 'incorrect'] as const).map(v => {
              const count = p.judge_verdict_counts?.[v] ?? 0
              if (count === 0) return null
              const s = JUDGE_STYLE[v]
              return (
                <div key={v} className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10px] font-semibold ${s.bg} ${s.border} ${s.text}`}>
                  <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${s.bar}`} />
                  {v} · {count}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Storage routing summary ── */}
      {Object.keys(routeCounts).length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10px] text-slate-600 uppercase tracking-wider font-medium">Storage used:</span>
          {Object.entries(routeCounts).map(([route, count]) => {
            const rs = routeStyle(route)
            return (
              <div key={route} className={`flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold ${rs.badge}`}>
                <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${rs.dot}`} />
                {rs.label} · {count}
              </div>
            )
          })}
        </div>
      )}

      {/* ── Answer cards ── */}
      {answers.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">
            {answers.length} Questions — Answered end-to-end
          </p>
          {answers.map((item, i) => (
            <AnswerCard
              key={item.index ?? item.query_type ?? i}
              item={item}
              defaultOpen={i === 0}
            />
          ))}
        </div>
      )}

      {/* ── Legend ── */}
      <div className="grid grid-cols-2 gap-1.5">
        {[
          { route: 'vector',   desc: 'Full-hybrid HNSW + BM25 + graph' },
          { route: 'kg',       desc: 'Entity graph traversal + semantic' },
          { route: 'sql',      desc: 'SQLite structured table query' },
          { route: 'sql+vec',  desc: 'SQL result + vector grounding' },
        ].map(({ route, desc }) => {
          const rs = routeStyle(route)
          return (
            <div key={route} className={`flex items-start gap-2 px-2 py-1.5 rounded-lg border ${rs.ring} bg-slate-900/30`}>
              <div className={`w-2 h-2 rounded-full mt-0.5 shrink-0 ${rs.dot}`} />
              <div>
                <p className={`text-[10px] font-bold ${rs.badge.split(' ').find(c => c.startsWith('text-')) ?? 'text-slate-300'}`}>
                  {rs.label}
                </p>
                <p className="text-[9px] text-slate-600 leading-relaxed">{desc}</p>
              </div>
            </div>
          )
        })}
      </div>

    </div>
  )
}
