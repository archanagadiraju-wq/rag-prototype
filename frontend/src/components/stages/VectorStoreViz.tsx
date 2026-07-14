import { useEffect, useState } from 'react'
import type { StageState } from '../../hooks/usePipelineStore'

interface SqlTableMeta {
  original_headers?: string[]
  columns: string[]
  row_count: number
  page?: number
  sample_rows?: string[][]
}

interface ChunkSample {
  id: string
  preview: string
  page?: number | null
  heading?: string | null
}

interface ChunkTypeGroup {
  count: number
  samples: ChunkSample[]
}

interface VectorStorePayload {
  collection?: string
  vectors_upserted?: number
  hnsw_m?: number
  hnsw_ef_construction?: number
  total_vectors_in_collection?: number
  upsert_ms?: number
  qdrant_live?: boolean
  sql_tables_created?: number
  sql_registry?: Record<string, SqlTableMeta>
  chunk_breakdown?: Record<string, ChunkTypeGroup>
}

const TYPE_META: Record<string, { label: string; color: string; border: string; badge: string }> = {
  prose:         { label: 'Prose',         color: 'text-indigo-300',  border: 'border-indigo-700/30',  badge: 'bg-indigo-900/40 text-indigo-300' },
  table_summary: { label: 'Table summary', color: 'text-amber-300',   border: 'border-amber-700/30',   badge: 'bg-amber-900/40 text-amber-300' },
  ocr_page:      { label: 'OCR page',      color: 'text-emerald-300', border: 'border-emerald-700/30', badge: 'bg-emerald-900/40 text-emerald-300' },
}

function fallbackMeta(type: string) {
  return { label: type, color: 'text-slate-300', border: 'border-slate-700/30', badge: 'bg-slate-800 text-slate-400' }
}

function ChunkGroup({ type, group }: { type: string; group: ChunkTypeGroup }) {
  const [open, setOpen] = useState(false)
  const meta = TYPE_META[type] ?? fallbackMeta(type)

  return (
    <div className={`rounded-lg border ${meta.border} overflow-hidden`}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-2.5 py-2 text-left hover:bg-white/5 transition-colors"
      >
        <span className={`text-[10px] font-semibold uppercase tracking-widest px-1.5 py-0.5 rounded ${meta.badge}`}>
          {meta.label}
        </span>
        <span className={`text-sm font-bold ${meta.color}`}>{group.count}</span>
        <span className="text-xs text-slate-500">chunk{group.count !== 1 ? 's' : ''}</span>
        <span className="ml-auto text-xs text-slate-600">{open ? '▲ hide' : '▼ show samples'}</span>
      </button>

      {open && (
        <div className="border-t border-[var(--color-border)] divide-y divide-[var(--color-border)]">
          {group.samples.map((s, i) => (
            <div key={s.id || i} className="px-2.5 py-2 bg-[var(--color-bg)]">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] font-mono text-slate-500">{s.id}</span>
                {s.page != null && <span className="text-[10px] text-slate-600">p.{s.page}</span>}
                {s.heading && <span className="text-[10px] text-slate-600 truncate max-w-[160px]">{s.heading}</span>}
              </div>
              <p className="text-xs text-slate-400 leading-relaxed whitespace-pre-wrap break-words">
                {s.preview}{s.preview.length >= 200 ? '…' : ''}
              </p>
            </div>
          ))}
          {group.count > group.samples.length && (
            <p className="px-2.5 py-1.5 text-[10px] text-slate-600 italic">
              +{group.count - group.samples.length} more chunks not shown
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export function VectorStoreViz({ stage }: { stage: StageState }) {
  const p = stage.payload as VectorStorePayload
  if (!p) return null

  const live      = p.qdrant_live ?? false
  const sqlCount  = p.sql_tables_created ?? 0
  const registry  = p.sql_registry ?? {}
  const breakdown = p.chunk_breakdown ?? {}
  const typeOrder = ['prose', 'table_summary', 'ocr_page',
                     ...Object.keys(breakdown).filter(k => !['prose','table_summary','ocr_page'].includes(k))]
  const orderedTypes = typeOrder.filter(k => breakdown[k])

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="px-3 py-2.5 rounded-lg bg-indigo-900/20 border border-indigo-700/30 text-xs text-slate-300 leading-relaxed">
        All chunk vectors were saved to Qdrant for semantic search. Document tables were also loaded into SQLite for precise numerical and aggregation queries.
      </div>

      {/* Online / offline status */}
      <div className={`flex items-start gap-3 px-3 py-3 rounded-lg border ${
        live ? 'bg-emerald-900/15 border-emerald-800/30' : 'bg-yellow-900/15 border-yellow-800/30'
      }`}>
        <span className={`w-2.5 h-2.5 rounded-full mt-0.5 flex-shrink-0 ${live ? 'bg-emerald-400' : 'bg-yellow-400'}`} />
        <div>
          <p className={`text-xs font-medium ${live ? 'text-emerald-300' : 'text-yellow-300'}`}>
            {live ? 'Qdrant is running — vectors are saved to disk' : 'Qdrant is offline — vectors are in memory only'}
          </p>
          <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">
            {live
              ? 'Vectors will persist across server restarts.'
              : 'Run "docker compose up qdrant" to enable persistence. The pipeline still works without it.'}
          </p>
        </div>
      </div>

      {/* Key stats */}
      <div>
        <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">What was saved</p>
        <div className="grid grid-cols-3 gap-1.5">
          <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
            <p className="text-lg font-bold text-white">{(p.vectors_upserted ?? 0).toLocaleString()}</p>
            <p className="text-xs text-slate-400">vectors saved</p>
            <p className="text-[10px] text-slate-600 mt-0.5">one per chunk</p>
          </div>
          <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
            <p className={`text-lg font-bold ${sqlCount > 0 ? 'text-amber-400' : 'text-slate-600'}`}>{sqlCount}</p>
            <p className="text-xs text-slate-400">SQL tables</p>
            <p className="text-[10px] text-slate-600 mt-0.5">from document</p>
          </div>
          <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
            <p className="text-lg font-bold text-white">{live ? `${(p.upsert_ms ?? 0).toFixed(0)}ms` : '—'}</p>
            <p className="text-xs text-slate-400">time to save</p>
          </div>
        </div>
      </div>

      {/* Chunk breakdown by type */}
      {orderedTypes.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
            Chunks in vector store — by type
          </p>
          <div className="space-y-1.5">
            {orderedTypes.map(type => (
              <ChunkGroup key={type} type={type} group={breakdown[type]} />
            ))}
          </div>
        </div>
      )}

      {/* SQL tables list */}
      {sqlCount > 0 && Object.keys(registry).length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">SQL Tables (SQLite)</p>
          <div className="rounded-lg bg-[var(--color-bg)] border border-amber-700/30 divide-y divide-[var(--color-border)]">
            {Object.entries(registry).map(([tname, meta]) => (
              <SqlTableRow key={tname} tname={tname} meta={meta} />
            ))}
          </div>
        </div>
      )}

      {/* Collection name */}
      {p.collection && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">Collection</p>
          <div className="px-2.5 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)]">
            <p className="text-xs font-mono text-indigo-300 break-all">{p.collection}</p>
            <p className="text-[10px] text-slate-600 mt-1">Each job gets its own collection to avoid mixing results from different documents.</p>
          </div>
        </div>
      )}

      {/* Index config */}
      <div>
        <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">Search index settings</p>
        <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] divide-y divide-[var(--color-border)]">
          <div className="flex items-start px-2.5 py-2 gap-2 text-xs">
            <span className="text-slate-500 w-28 shrink-0">Index type</span>
            <div>
              <p className="text-slate-300">HNSW (Hierarchical Navigable Small World)</p>
              <p className="text-[10px] text-slate-600 mt-0.5">A graph-based algorithm — searches by hopping between nearby vectors. Very fast even at large scale.</p>
            </div>
          </div>
          <div className="flex items-center px-2.5 py-2 gap-2 text-xs">
            <span className="text-slate-500 w-28 shrink-0">Connectivity (m)</span>
            <span className="text-slate-300">{p.hnsw_m ?? 8} neighbours per node</span>
          </div>
          <div className="flex items-center px-2.5 py-2 gap-2 text-xs">
            <span className="text-slate-500 w-28 shrink-0">Build quality</span>
            <span className="text-slate-300">ef={p.hnsw_ef_construction ?? 100} — higher = more accurate index, slower to build</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── SQL table row + modal ─────────────────────────────────────────────────────

function SqlTableRow({ tname, meta }: { tname: string; meta: SqlTableMeta }) {
  const [open, setOpen] = useState(false)
  const headers = meta.original_headers ?? meta.columns ?? []
  const sample  = meta.sample_rows ?? []
  const hasRows = sample.length > 0

  return (
    <>
      <div className="px-2.5 py-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] font-mono text-amber-300 truncate">{tname}</span>
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-[10px] text-slate-500">
              {meta.row_count} rows{meta.page != null ? ` · p.${meta.page}` : ''}
            </span>
            {hasRows && (
              <button
                onClick={() => setOpen(true)}
                className="text-[10px] text-amber-400 hover:text-amber-300 underline-offset-2 hover:underline transition-colors"
                title="Preview rows stored in SQLite"
              >
                view rows ↗
              </button>
            )}
          </div>
        </div>
        <p className="text-[9px] text-slate-600 mt-0.5 font-mono truncate">
          {(meta.columns ?? []).join(', ')}
        </p>
      </div>
      {open && (
        <SqlTableModal
          tname={tname}
          headers={headers}
          rows={sample}
          rowCount={meta.row_count}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  )
}

function SqlTableModal({
  tname, headers, rows, rowCount, onClose,
}: {
  tname: string
  headers: string[]
  rows: string[][]
  rowCount: number
  onClose: () => void
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const showing = rows.length
  const truncated = rowCount > showing

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-5xl max-h-[85vh] flex flex-col rounded-xl bg-[var(--color-surface)] border border-[var(--color-border)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium mb-1">
              SQL table preview
            </p>
            <p className="text-sm text-amber-300 font-mono truncate">{tname}</p>
            <p className="text-[10px] text-slate-500 mt-0.5">
              {headers.length} column{headers.length === 1 ? '' : 's'} · {rowCount} row{rowCount === 1 ? '' : 's'} total
              {truncated && <span className="text-slate-600"> · showing first {showing}</span>}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-white text-xl leading-none px-2"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-[var(--color-surface)] z-10">
              <tr className="border-b border-[var(--color-border)]">
                {headers.map((h, i) => (
                  <th key={i} className="text-left px-3 py-2 font-medium text-amber-400 whitespace-nowrap">
                    {h || <span className="text-slate-600 italic">col{i + 1}</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr
                  key={ri}
                  className={`border-b border-[var(--color-border)] ${ri % 2 ? 'bg-slate-900/30' : ''}`}
                >
                  {headers.map((_, ci) => (
                    <td key={ci} className="px-3 py-1.5 font-mono text-slate-300 whitespace-nowrap">
                      {r[ci] ?? ''}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="px-4 py-2 border-t border-[var(--color-border)] flex items-center justify-between text-[10px] text-slate-500">
          <span>
            {truncated
              ? `Showing first ${showing} of ${rowCount} rows`
              : `${rowCount} row${rowCount === 1 ? '' : 's'}`}
          </span>
          <span>Esc or click outside to close</span>
        </div>
      </div>
    </div>
  )
}
