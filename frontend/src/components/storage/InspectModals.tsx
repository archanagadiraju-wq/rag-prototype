import { useEffect, useState, useCallback } from 'react'

// Cap rendered chunk text. The CID-encoded garbage from font-broken PDFs
// produces single 50KB+ unbreakable strings — laying those out in a width-
// constrained container will hang Chrome's text engine. The user can fetch
// the full chunk via the API if they really need it.
const MAX_TEXT_CHARS = 2000

// ── Shared shell ─────────────────────────────────────────────────────────────

function ModalShell({
  title,
  subtitle,
  onClose,
  children,
  toolbar,
}: {
  title: string
  subtitle?: string
  onClose: () => void
  children: React.ReactNode
  toolbar?: React.ReactNode
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-6xl max-h-[90vh] flex flex-col rounded-xl bg-[var(--color-surface)] border border-[var(--color-border)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium mb-1">
              {title}
            </p>
            {subtitle && <p className="text-xs text-slate-400">{subtitle}</p>}
          </div>
          {toolbar}
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-white text-xl leading-none px-2"
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-auto p-3">
          {children}
        </div>
      </div>
    </div>
  )
}

function Pager({
  total, offset, limit, onChange,
}: {
  total: number
  offset: number
  limit: number
  onChange: (newOffset: number) => void
}) {
  const start = total === 0 ? 0 : offset + 1
  const end = Math.min(offset + limit, total)
  const canPrev = offset > 0
  const canNext = offset + limit < total
  return (
    <div className="flex items-center gap-2 text-[11px] text-slate-400 font-mono">
      <span>{start}–{end} / {total}</span>
      <button
        onClick={() => onChange(Math.max(0, offset - limit))}
        disabled={!canPrev}
        className="px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-indigo-500 disabled:opacity-30 disabled:cursor-not-allowed"
      >
        ← prev
      </button>
      <button
        onClick={() => onChange(offset + limit)}
        disabled={!canNext}
        className="px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-indigo-500 disabled:opacity-30 disabled:cursor-not-allowed"
      >
        next →
      </button>
    </div>
  )
}


// ── 1. Chunk Inspector (Qdrant / vector DB) ─────────────────────────────────

interface ChunkItem {
  chunk_id: string
  text: string
  token_count: number | null
  page: number | null
  heading_path: string | null
  chunk_type: string | null
  table_name: string | null
  doc_id: string | null
  vector_preview: number[]
  has_vector: boolean
}

interface ChunksResponse {
  total: number
  offset: number
  limit: number
  chunk_types: string[]
  items: ChunkItem[]
}

export function ChunkInspector({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const [data, setData] = useState<ChunksResponse | null>(null)
  const [offset, setOffset] = useState(0)
  const [limit] = useState(25)
  const [filter, setFilter] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
      if (filter) params.set('chunk_type', filter)
      const r = await fetch(`/api/jobs/${jobId}/inspect/chunks?${params}`)
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setError(d.detail || `${r.status}`)
      } else {
        setData(await r.json())
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'fetch failed')
    } finally {
      setLoading(false)
    }
  }, [jobId, offset, limit, filter])

  useEffect(() => { void load() }, [load])

  return (
    <ModalShell
      title="Vector DB · embedded chunks"
      subtitle={data ? `${data.total} chunks${filter ? ` filtered (chunk_type=${filter})` : ''}` : undefined}
      onClose={onClose}
      toolbar={
        <div className="flex items-center gap-2 text-[11px]">
          <span className="text-slate-500">type</span>
          <select
            value={filter}
            onChange={(e) => { setFilter(e.target.value); setOffset(0) }}
            className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded px-2 py-1 font-mono"
          >
            <option value="">all</option>
            {(data?.chunk_types ?? []).map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          {data && <Pager total={data.total} offset={offset} limit={limit} onChange={setOffset} />}
        </div>
      }
    >
      {error && <p className="text-red-400 text-sm">⚠ {error}</p>}
      {loading && !data && <p className="text-slate-500 text-sm">Loading…</p>}

      {data?.items.length === 0 && (
        <p className="text-slate-500 text-sm italic">No chunks match this filter.</p>
      )}

      <div className="space-y-2">
        {data?.items.map((c) => (
          <div key={c.chunk_id} className="rounded-lg border border-[var(--color-border)] bg-slate-900/30 p-3 text-xs">
            <div className="flex items-center justify-between gap-3 mb-1.5">
              <span className="font-mono text-indigo-300">{c.chunk_id}</span>
              <div className="flex gap-2 text-[10px] font-mono">
                {c.chunk_type && (
                  <span className={`px-1.5 py-0.5 rounded ${
                    c.chunk_type === 'table_summary' ? 'bg-amber-900/40 text-amber-300' :
                    c.chunk_type === 'ocr_prose' ? 'bg-rose-900/40 text-rose-300' :
                    'bg-slate-800 text-slate-400'
                  }`}>{c.chunk_type}</span>
                )}
                {c.table_name && (
                  <span className="px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-300">{c.table_name}</span>
                )}
                {c.page != null && <span className="text-slate-500">p{c.page}</span>}
                {c.token_count != null && <span className="text-slate-500">{c.token_count} tok</span>}
                <span className={c.has_vector ? 'text-emerald-400' : 'text-rose-400'}>
                  {c.has_vector ? '✓ vec' : '✗ no vec'}
                </span>
              </div>
            </div>
            {c.heading_path && (
              <p className="text-[10px] text-slate-500 mb-1 truncate">↳ {c.heading_path}</p>
            )}
            <p className="text-slate-300 whitespace-pre-wrap break-all leading-snug max-h-48 overflow-y-auto">
              {c.text.length > MAX_TEXT_CHARS
                ? c.text.slice(0, MAX_TEXT_CHARS)
                : c.text}
              {c.text.length > MAX_TEXT_CHARS && (
                <span className="text-slate-500 italic">
                  {' '}… (+{(c.text.length - MAX_TEXT_CHARS).toLocaleString()} more chars truncated for safe rendering)
                </span>
              )}
            </p>
            {c.vector_preview.length > 0 && (
              <pre className="mt-1.5 text-[9px] font-mono text-indigo-400/60 bg-slate-950/60 rounded px-2 py-1 overflow-x-auto">
                vec[0..7] = [{c.vector_preview.map((x) => x.toFixed(5)).join(', ')}, …]
              </pre>
            )}
          </div>
        ))}
      </div>
    </ModalShell>
  )
}


// ── 2. SQL Inspector (SQLite per-table row browser) ─────────────────────────

interface SqlRow {
  row_index: number
  cells: Record<string, unknown>
}

interface SqlResponse {
  table_name: string
  columns: string[]
  total: number
  offset: number
  limit: number
  rows: SqlRow[]
}

export function SqlInspector({
  jobId, tableNames, initialTable, onClose,
}: {
  jobId: string
  tableNames: string[]
  initialTable: string
  onClose: () => void
}) {
  const [activeTable, setActiveTable] = useState(initialTable)
  const [offset, setOffset] = useState(0)
  const [limit] = useState(50)
  const [data, setData] = useState<SqlResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const r = await fetch(`/api/jobs/${jobId}/inspect/sql/${activeTable}?offset=${offset}&limit=${limit}`)
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setError(d.detail || `${r.status}`)
        setData(null)
      } else {
        setData(await r.json())
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'fetch failed')
    } finally {
      setLoading(false)
    }
  }, [jobId, activeTable, offset, limit])

  useEffect(() => { void load() }, [load])

  return (
    <ModalShell
      title="SQLite · row browser"
      subtitle={
        data
          ? `${data.table_name} · ${data.columns.length} columns · ${data.total} rows total`
          : undefined
      }
      onClose={onClose}
      toolbar={data && <Pager total={data.total} offset={offset} limit={limit} onChange={setOffset} />}
    >
      <div className="mb-3 flex flex-wrap gap-1.5">
        {tableNames.map((t) => (
          <button
            key={t}
            onClick={() => { setActiveTable(t); setOffset(0) }}
            className={`px-2 py-1 text-[11px] font-mono rounded border ${
              t === activeTable
                ? 'border-amber-500 bg-amber-900/30 text-amber-300'
                : 'border-[var(--color-border)] text-slate-400 hover:border-amber-500/50'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {error && <p className="text-red-400 text-sm">⚠ {error}</p>}
      {loading && !data && <p className="text-slate-500 text-sm">Loading…</p>}

      {data && (
        <div className="overflow-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-[var(--color-surface)] z-10">
              <tr className="border-b border-[var(--color-border)]">
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-12">#</th>
                {data.columns.map((h) => (
                  <th key={h} className="text-left px-3 py-2 font-medium text-amber-400 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.row_index} className={`border-b border-[var(--color-border)] ${r.row_index % 2 ? 'bg-slate-900/30' : ''}`}>
                  <td className="px-3 py-1.5 font-mono text-slate-600">{r.row_index}</td>
                  {data.columns.map((col) => (
                    <td key={col} className="px-3 py-1.5 font-mono text-slate-300 whitespace-nowrap">
                      {String(r.cells[col] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </ModalShell>
  )
}


// ── 3. KG Inspector (nodes + neighbours) ────────────────────────────────────

interface KgNode {
  key: string
  type: string
  label: string | null
  text: string | null
  attrs: Record<string, unknown>
  degree: number
}

interface KgEdge {
  source: string
  target: string
  weight: number
  rel: string | null
}

interface KgDetail {
  node: KgNode
  neighbours: KgNode[]
  edges: KgEdge[]
}

interface KgResponse {
  total_nodes: number
  total_edges: number
  node_types: Record<string, number>
  offset: number
  limit: number
  items: KgNode[]
  detail: KgDetail | null
}

const TYPE_COLORS: Record<string, string> = {
  document: 'text-cyan-300',
  table:    'text-amber-300',
  chunk:    'text-indigo-300',
  entity:   'text-violet-300',
}

function NodeBadge({ n, onClick }: { n: KgNode; onClick?: () => void }) {
  const color = TYPE_COLORS[n.type] || 'text-slate-300'
  return (
    <button
      onClick={onClick}
      disabled={!onClick}
      className={`text-left text-[11px] font-mono ${color} truncate hover:underline disabled:no-underline disabled:cursor-default`}
    >
      {n.key}
    </button>
  )
}

export function KgInspector({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const [data, setData] = useState<KgResponse | null>(null)
  const [offset, setOffset] = useState(0)
  const [limit] = useState(50)
  const [nodeType, setNodeType] = useState('')
  const [q, setQ] = useState('')
  const [focus, setFocus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
      if (nodeType) params.set('node_type', nodeType)
      if (q) params.set('q', q)
      if (focus) params.set('focus', focus)
      const r = await fetch(`/api/jobs/${jobId}/inspect/kg?${params}`)
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setError(d.detail || `${r.status}`)
      } else {
        setData(await r.json())
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'fetch failed')
    } finally {
      setLoading(false)
    }
  }, [jobId, offset, limit, nodeType, q, focus])

  useEffect(() => { void load() }, [load])

  const filteredCount = data
    ? (nodeType ? (data.node_types[nodeType] ?? 0) : data.total_nodes)
    : 0

  return (
    <ModalShell
      title="Knowledge graph · nodes & edges"
      subtitle={
        data
          ? `${data.total_nodes} nodes · ${data.total_edges} edges` +
            (data.node_types
              ? ' · ' + Object.entries(data.node_types).map(([k, v]) => `${k}:${v}`).join(' · ')
              : '')
          : undefined
      }
      onClose={onClose}
      toolbar={
        <div className="flex items-center gap-2 text-[11px]">
          <select
            value={nodeType}
            onChange={(e) => { setNodeType(e.target.value); setOffset(0); setFocus(null) }}
            className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded px-2 py-1 font-mono"
          >
            <option value="">all types</option>
            {data && Object.keys(data.node_types).map((t) => (
              <option key={t} value={t}>{t} ({data.node_types[t]})</option>
            ))}
          </select>
          <input
            value={q}
            onChange={(e) => { setQ(e.target.value); setOffset(0); setFocus(null) }}
            placeholder="filter by key…"
            className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded px-2 py-1 font-mono w-40"
          />
          {data && <Pager total={filteredCount} offset={offset} limit={limit} onChange={setOffset} />}
        </div>
      }
    >
      {error && <p className="text-red-400 text-sm">⚠ {error}</p>}
      {loading && !data && <p className="text-slate-500 text-sm">Loading…</p>}

      <div className="grid grid-cols-2 gap-3 min-h-0">
        {/* Left — node list */}
        <div className="overflow-auto rounded-lg border border-[var(--color-border)] bg-slate-900/30 p-2 space-y-1 max-h-[65vh]">
          {data?.items.length === 0 && (
            <p className="text-slate-500 text-xs italic">No nodes match this filter.</p>
          )}
          {data?.items.map((n) => (
            <div
              key={n.key}
              onClick={() => setFocus(n.key)}
              className={`px-2 py-1 rounded cursor-pointer hover:bg-slate-800/60 ${
                focus === n.key ? 'bg-slate-800 ring-1 ring-indigo-500/40' : ''
              }`}
            >
              <div className="flex items-center justify-between gap-2 text-[11px]">
                <span className={`font-mono truncate ${TYPE_COLORS[n.type] || 'text-slate-300'}`}>
                  {n.key}
                </span>
                <span className="text-[10px] text-slate-500 shrink-0">deg {n.degree}</span>
              </div>
              {n.text && n.text !== n.key && (
                <p className="text-[10px] text-slate-500 truncate">{n.text}</p>
              )}
            </div>
          ))}
        </div>

        {/* Right — focus detail */}
        <div className="overflow-auto rounded-lg border border-[var(--color-border)] bg-slate-900/30 p-3 text-xs max-h-[65vh]">
          {!data?.detail ? (
            <p className="text-slate-500 italic text-xs">
              Click any node on the left to see its neighbours and edges.
            </p>
          ) : (
            <>
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Focused node</p>
              <p className={`font-mono text-sm ${TYPE_COLORS[data.detail.node.type] || 'text-slate-200'}`}>
                {data.detail.node.key}
              </p>
              <p className="text-[10px] text-slate-500 mb-2">
                type <span className="text-slate-400">{data.detail.node.type}</span>
                {data.detail.node.label && <> · label <span className="text-slate-400">{data.detail.node.label}</span></>}
                {' · '}degree <span className="text-slate-400">{data.detail.node.degree}</span>
              </p>

              {Object.keys(data.detail.node.attrs).length > 0 && (
                <details className="mb-3 text-[10px]">
                  <summary className="cursor-pointer text-slate-500 hover:text-slate-300">node attrs</summary>
                  <pre className="mt-1 font-mono text-slate-400 bg-slate-950/60 rounded px-2 py-1 overflow-x-auto">
                    {JSON.stringify(data.detail.node.attrs, null, 2)}
                  </pre>
                </details>
              )}

              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 mt-2">
                Neighbours ({data.detail.neighbours.length})
              </p>
              <div className="space-y-1">
                {data.detail.neighbours.slice(0, 100).map((nb, i) => {
                  const e = data.detail!.edges[i]
                  return (
                    <div key={nb.key} className="flex items-center justify-between gap-2 px-2 py-1 hover:bg-slate-800/40 rounded">
                      <NodeBadge n={nb} onClick={() => setFocus(nb.key)} />
                      <span className="text-[10px] text-slate-500 font-mono shrink-0">
                        {e?.rel || 'edge'} · w={e?.weight ?? 1}
                      </span>
                    </div>
                  )
                })}
                {data.detail.neighbours.length > 100 && (
                  <p className="text-[10px] text-slate-500 italic px-2 py-1">
                    + {(data.detail.neighbours.length - 100).toLocaleString()} more neighbours not shown (high-degree hub)
                  </p>
                )}
                {data.detail.neighbours.length === 0 && (
                  <p className="text-slate-500 italic">No neighbours.</p>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </ModalShell>
  )
}
