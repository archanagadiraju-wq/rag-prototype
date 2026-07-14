import { useState } from 'react'
import type { StageState } from '../../hooks/usePipelineStore'
import type { RetrievalResult } from '../../types/events'

// ── Types ─────────────────────────────────────────────────────────────────────

interface VectorResult {
  rank: number
  chunk_id: string
  text: string
  dense_score: number
  sparse_score: number
  graph_score: number
}

interface ShowcaseQuestion {
  index: number
  question: string
  route: string
  type: string
  difficulty: string
  sql_fallback?: boolean
  table?: string
  vector_results: VectorResult[]
  sql_query?: string
  sql_cols?: string[]
  sql_rows?: (string | number)[][]
  retrieval_ms?: number
}

interface RAGReadyPayload {
  test_query?: string
  retrieval_results?: RetrievalResult[]
  total_retrieval_ms?: number
  retrieval_mode?: string
  query_showcase?: ShowcaseQuestion[]
  routing_summary?: {
    total_questions: number
    vector_count: number
    kg_count: number
    sql_count: number
    hybrid_count: number
    sql_available: boolean
    tables_found: number
  }
}

// ── Route styling ─────────────────────────────────────────────────────────────

const ROUTE_STYLE: Record<string, { label: string; badge: string; ring: string; icon: string }> = {
  vector:    { label: 'Vector DB',    badge: 'bg-indigo-900/50 border-indigo-600/50 text-indigo-300',     ring: 'border-indigo-700/30',   icon: '◈' },
  kg:        { label: 'Graph',        badge: 'bg-violet-900/50 border-violet-600/50 text-violet-300',     ring: 'border-violet-700/30',   icon: '⬡' },
  sql:       { label: 'SQL',          badge: 'bg-amber-900/50 border-amber-600/50 text-amber-300',        ring: 'border-amber-700/30',    icon: '⊞' },
  'sql+vec': { label: 'SQL + Vector', badge: 'bg-emerald-900/50 border-emerald-600/50 text-emerald-300',  ring: 'border-emerald-700/30',  icon: '⊞◈' },
  'vec+sql': { label: 'Vector + SQL', badge: 'bg-emerald-900/50 border-emerald-600/50 text-emerald-300',  ring: 'border-emerald-700/30',  icon: '◈⊞' },
}

const DIFF_STYLE: Record<string, string> = {
  easy:   'text-emerald-400 bg-emerald-900/20 border-emerald-700/30',
  medium: 'text-amber-400   bg-amber-900/20   border-amber-700/30',
  hard:   'text-red-400     bg-red-900/20     border-red-700/30',
}

const TYPE_LABEL: Record<string, string> = {
  semantic:  'Semantic',
  keyword:   'Keyword',
  entity:    'Entity-Graph',
  numerical: 'Numerical',
  hybrid:    'Hybrid',
}

function routeStyle(route: string) {
  return ROUTE_STYLE[route] ?? ROUTE_STYLE.vector
}

// ── SQL result table ──────────────────────────────────────────────────────────

function SqlTable({ cols, rows }: { cols: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[10px] border-collapse">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c} className="px-2 py-1 text-left text-slate-400 font-semibold border border-slate-700/40 bg-slate-800/60">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className={ri % 2 === 0 ? 'bg-slate-900/30' : 'bg-slate-800/20'}>
              {row.map((cell, ci) => (
                <td key={ci} className="px-2 py-1 text-slate-300 border border-slate-700/30 font-mono">
                  {String(cell ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Question card ─────────────────────────────────────────────────────────────

function QuestionCard({ q, defaultOpen }: { q: ShowcaseQuestion; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const rs = routeStyle(q.route)

  const hasSQL = !!(q.sql_cols?.length && q.sql_rows?.length)
  const hasVec = q.vector_results.length > 0

  return (
    <div className={`rounded-xl border overflow-hidden bg-[var(--color-bg)] ${rs.ring}`}>
      {/* Header */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full text-left px-3 py-3 flex items-start gap-3 hover:bg-slate-800/30 transition-colors"
      >
        {/* Number */}
        <span className="text-[10px] font-bold text-slate-500 shrink-0 mt-0.5 w-4 text-right">
          {q.index}
        </span>

        <div className="flex-1 min-w-0 space-y-1.5">
          {/* Badges row */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded border whitespace-nowrap ${rs.badge}`}>
              {rs.icon} {rs.label}
            </span>
            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${DIFF_STYLE[q.difficulty] ?? DIFF_STYLE.medium}`}>
              {q.difficulty}
            </span>
            <span className="text-[10px] text-slate-600">
              {TYPE_LABEL[q.type] ?? q.type}
            </span>
            {q.sql_fallback && (
              <span className="text-[10px] text-yellow-500 bg-yellow-900/20 border border-yellow-700/30 px-1.5 py-0.5 rounded">
                no tables → vector fallback
              </span>
            )}
          </div>
          {/* Question */}
          <p className="text-xs text-slate-300 leading-snug">{q.question}</p>
        </div>

        {/* Right side */}
        <div className="flex items-center gap-1.5 shrink-0">
          {hasSQL && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/20 border border-amber-700/30 text-amber-400">
              SQL ✓
            </span>
          )}
          {q.retrieval_ms != null && (
            <span className="text-[10px] text-slate-600 font-mono whitespace-nowrap">
              {q.retrieval_ms < 1000 ? `${q.retrieval_ms.toFixed(0)}ms` : `${(q.retrieval_ms / 1000).toFixed(2)}s`}
            </span>
          )}
          <span className="text-slate-600 text-xs ml-1">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-[var(--color-border)] space-y-0">
          {/* SQL result */}
          {hasSQL && (
            <div className="px-3 py-2.5 bg-amber-900/5 border-b border-[var(--color-border)]">
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-[10px] font-bold text-amber-400 uppercase tracking-wider">SQL result</span>
                {q.table && <span className="text-[10px] text-slate-600 font-mono">{q.table}</span>}
              </div>
              <SqlTable cols={q.sql_cols!} rows={q.sql_rows!} />
              {q.sql_query && (
                <details className="mt-1.5">
                  <summary className="text-[10px] text-slate-600 cursor-pointer hover:text-slate-400">show SQL query</summary>
                  <pre className="mt-1 text-[10px] text-slate-500 bg-slate-900/40 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                    {q.sql_query}
                  </pre>
                </details>
              )}
            </div>
          )}

          {/* Vector results */}
          {hasVec && (
            <div className="px-3 py-2.5">
              <p className="text-[10px] font-bold text-indigo-400 uppercase tracking-wider mb-1.5">
                Vector retrieval — top {q.vector_results.length} chunks
              </p>
              <div className="space-y-1">
                {q.vector_results.map((r) => (
                  <div key={r.chunk_id} className="flex items-start gap-2 px-2 py-1.5 rounded bg-slate-800/30 border border-slate-700/20">
                    <span className="text-[10px] font-bold text-slate-500 shrink-0">#{r.rank}</span>
                    <p className="text-[11px] text-slate-400 line-clamp-2 flex-1">{r.text}</p>
                    <div className="flex gap-1 shrink-0">
                      {r.dense_score > 0 && (
                        <span className="text-[9px] text-indigo-400 font-mono">{(r.dense_score * 100).toFixed(0)}%</span>
                      )}
                      {r.graph_score > 0 && (
                        <span className="text-[9px] text-violet-400 font-mono">+G</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Result modal (Final Results tab) ─────────────────────────────────────────

function ScoreBar({ value, color, label }: { value: number; color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[9px] text-slate-600 w-10 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, value * 100)}%` }} />
      </div>
      <span className="text-[10px] font-mono text-slate-400 w-7 text-right">{(value * 100).toFixed(0)}%</span>
    </div>
  )
}

function ResultModal({ result, rank, onClose }: { result: RetrievalResult; rank: number; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl w-full max-w-2xl max-h-[75vh] flex flex-col shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
          <p className="text-sm font-semibold text-white">Result #{rank}</p>
          <button onClick={onClose} className="text-slate-500 hover:text-white text-lg leading-none">×</button>
        </div>
        <div className="px-4 py-3 border-b border-[var(--color-border)] bg-slate-900/40 space-y-1.5">
          <ScoreBar value={result.dense_score} color="bg-indigo-500"  label="Meaning" />
          <ScoreBar value={result.sparse_score} color="bg-emerald-500" label="Keywords" />
          <ScoreBar value={(result as any).graph_score ?? 0} color="bg-violet-500" label="Graph" />
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">{result.text}</p>
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function RAGReadyViz({ stage }: { stage: StageState }) {
  const p = stage.payload as RAGReadyPayload
  const [activeTab, setActiveTab] = useState<'showcase' | 'results'>('showcase')
  const [selected, setSelected] = useState<{ result: RetrievalResult; rank: number } | null>(null)

  if (!p) return null

  const showcase = p.query_showcase ?? []
  const summary  = p.routing_summary
  const results  = p.retrieval_results ?? []

  return (
    <>
      <div className="space-y-4">

        {/* Intro */}
        <div className="px-3 py-2.5 rounded-lg bg-indigo-900/20 border border-indigo-700/30 text-xs text-slate-300 leading-relaxed">
          10 document-specific questions were routed to the most effective storage mechanism —
          semantic questions go to the vector DB, entity questions traverse the knowledge graph,
          and numerical questions are answered by running SQL against the extracted table data.
        </div>

        {/* Storage mechanism legend */}
        <div className="grid grid-cols-2 gap-1.5 text-[10px]">
          <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg border bg-indigo-900/20 border-indigo-700/30 text-indigo-300">
            <span className="font-bold">◈ Vector DB</span>
            <span className="text-slate-500">— semantic meaning + keyword + KG</span>
          </div>
          <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg border bg-amber-900/20 border-amber-700/30 text-amber-300">
            <span className="font-bold">⊞ SQL</span>
            <span className="text-slate-500">— precise calculations on table data</span>
          </div>
          <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg border bg-violet-900/20 border-violet-700/30 text-violet-300">
            <span className="font-bold">⬡ Graph</span>
            <span className="text-slate-500">— entity relationships + co-occurrence</span>
          </div>
          <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg border bg-emerald-900/20 border-emerald-700/30 text-emerald-300">
            <span className="font-bold">⊞◈ Hybrid</span>
            <span className="text-slate-500">— SQL precision + semantic context</span>
          </div>
        </div>

        {/* Routing summary chips */}
        {summary && (
          <div className="flex gap-2 flex-wrap text-[10px]">
            <span className="px-2 py-1 rounded bg-slate-800/40 border border-slate-700/30 text-slate-400">
              {summary.total_questions} questions total
            </span>
            <span className="px-2 py-1 rounded bg-indigo-900/20 border border-indigo-700/30 text-indigo-300">
              {summary.vector_count} → vector
            </span>
            {summary.kg_count > 0 && (
              <span className="px-2 py-1 rounded bg-violet-900/20 border border-violet-700/30 text-violet-300">
                {summary.kg_count} → graph
              </span>
            )}
            {summary.sql_available ? (
              <span className="px-2 py-1 rounded bg-amber-900/20 border border-amber-700/30 text-amber-300">
                {summary.sql_count + summary.hybrid_count} → SQL · {summary.tables_found} table(s) indexed
              </span>
            ) : (
              <span className="px-2 py-1 rounded bg-yellow-900/20 border border-yellow-700/30 text-yellow-400">
                no tables — SQL → vector fallback
              </span>
            )}
          </div>
        )}

        {/* Tab switcher */}
        <div className="flex gap-1 bg-slate-800/40 rounded-lg p-1">
          <button
            onClick={() => setActiveTab('showcase')}
            className={`flex-1 py-1 rounded-md text-xs font-medium transition-all ${activeTab === 'showcase' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
          >
            Query Showcase (10)
          </button>
          <button
            onClick={() => setActiveTab('results')}
            className={`flex-1 py-1 rounded-md text-xs font-medium transition-all ${activeTab === 'results' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
          >
            Final Results
          </button>
        </div>

        {/* Showcase tab */}
        {activeTab === 'showcase' && (
          <div className="space-y-2">
            {showcase.map((q, i) => (
              <QuestionCard key={q.index} q={q} defaultOpen={i === 0} />
            ))}
          </div>
        )}

        {/* Final results tab */}
        {activeTab === 'results' && (
          <div className="space-y-3">
            <div className="px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-700/30">
              <p className="text-[10px] text-slate-500 mb-0.5">Primary semantic query</p>
              <p className="text-xs text-slate-300 italic">"{p.test_query}"</p>
              <p className="text-[10px] text-slate-600 mt-1">{p.retrieval_mode} · {(p.total_retrieval_ms ?? 0).toFixed(0)}ms</p>
            </div>
            {results.length > 0 && (
              <div className="space-y-1.5">
                {results.map((r) => (
                  <button
                    key={r.chunk_id}
                    onClick={() => setSelected({ result: r, rank: r.final_rank })}
                    className="w-full text-left rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-2.5 py-2.5 hover:border-indigo-500/50 hover:bg-indigo-500/5 transition-all group"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="w-5 h-5 rounded-full bg-slate-700 flex items-center justify-center text-[10px] font-bold text-slate-300 shrink-0">
                        {r.final_rank}
                      </span>
                      <span className="text-[10px] text-slate-600 font-mono truncate flex-1">{r.chunk_id}</span>
                      <span className="text-[10px] text-slate-600 group-hover:text-slate-400 shrink-0">read ↗</span>
                    </div>
                    <p className="text-xs text-slate-400 line-clamp-2 leading-relaxed">{r.text}</p>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

      </div>

      {selected && (
        <ResultModal result={selected.result} rank={selected.rank} onClose={() => setSelected(null)} />
      )}
    </>
  )
}
