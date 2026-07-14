import { useEffect, useState } from 'react'
import { JobSummary } from './JobSummary'
import { ChunkInspector, SqlInspector, KgInspector } from './InspectModals'

interface Qdrant {
  collection: string | null
  vectors: number
  dimensions: number
  live: boolean
  distance: string
  hnsw_m: number
  hnsw_ef_construct: number
  embedding_model: string
  sample_vector: number[]
}

interface SqliteTable {
  name: string
  rows: number
  columns: string[]
}

interface Sqlite {
  file: string | null
  size_bytes: number
  tables: SqliteTable[]
}

interface Bm25 {
  unique_terms: number
  doc_count: number
  avg_doc_len: number
}

interface Kg {
  nodes: number
  edges: number
  entity_types: string[]
}

interface DiskFile {
  name: string
  size_bytes: number
}

interface Disk {
  path: string
  total_bytes: number
  file_count: number
  files: DiskFile[]
}

interface InMemory {
  key_count: number
  keys: string[]
}

interface StorageSummaryData {
  job_id: string
  exists: boolean
  qdrant: Qdrant
  sqlite: Sqlite
  bm25: Bm25
  kg: Kg
  disk: Disk
  cache: InMemory
}


function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}


function Section({
  icon, title, accent, summary, children, onInspect,
}: {
  icon: string
  title: string
  accent: 'indigo' | 'amber' | 'emerald' | 'violet' | 'slate' | 'cyan'
  summary: string
  children?: React.ReactNode
  onInspect?: () => void
}) {
  const colors = {
    indigo:  { border: 'border-indigo-500/30',  text: 'text-indigo-300',  bg: 'bg-indigo-900/10'  },
    amber:   { border: 'border-amber-500/30',   text: 'text-amber-300',   bg: 'bg-amber-900/10'   },
    emerald: { border: 'border-emerald-500/30', text: 'text-emerald-300', bg: 'bg-emerald-900/10' },
    violet:  { border: 'border-violet-500/30',  text: 'text-violet-300',  bg: 'bg-violet-900/10'  },
    slate:   { border: 'border-slate-600/40',   text: 'text-slate-300',   bg: 'bg-slate-900/30'   },
    cyan:    { border: 'border-cyan-500/30',    text: 'text-cyan-300',    bg: 'bg-cyan-900/10'    },
  }
  const c = colors[accent]
  return (
    <div className={`rounded-xl border ${c.border} ${c.bg} overflow-hidden`}>
      <div className="px-3 py-2 flex items-center gap-2 border-b border-[var(--color-border)]">
        <span className="text-base">{icon}</span>
        <span className={`text-xs font-semibold ${c.text} uppercase tracking-wider`}>{title}</span>
        <span className="text-xs text-slate-400 ml-auto font-mono">{summary}</span>
        {onInspect && (
          <button
            onClick={onInspect}
            className={`text-[10px] ${c.text} hover:underline underline-offset-2 font-medium`}
          >
            inspect →
          </button>
        )}
      </div>
      {children && <div className="p-3 text-xs space-y-1">{children}</div>}
    </div>
  )
}


export function StorageSummary({ jobId }: { jobId: string | null }) {
  const [data, setData] = useState<StorageSummaryData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [inspect, setInspect] = useState<null | 'chunks' | 'sql' | 'kg'>(null)
  const [sqlInitial, setSqlInitial] = useState<string>('')

  async function refresh() {
    if (!jobId) return
    setLoading(true); setError(null)
    try {
      const r = await fetch(`/api/jobs/${jobId}/storage`)
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setError(d.detail || `${r.status} ${r.statusText}`)
        setData(null)
      } else {
        setData(await r.json())
      }
    } catch (exc: unknown) {
      setError(exc instanceof Error ? exc.message : 'request failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void refresh() }, [jobId])

  if (!jobId) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-600 text-xs">
        No active job.
      </div>
    )
  }

  if (loading && !data) {
    return <div className="flex-1 flex items-center justify-center text-slate-500 text-xs">Loading storage summary…</div>
  }

  if (error) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-slate-500 text-xs gap-2 p-6">
        <p className="text-red-400">⚠ {error}</p>
        <button onClick={refresh} className="text-indigo-400 hover:text-indigo-300 underline-offset-2 hover:underline">
          retry
        </button>
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">

      {/* ── JOB SUMMARY — totals at the top, always ── */}
      <JobSummary jobId={jobId} />

      <div className="flex items-center justify-between pt-2 border-t border-[var(--color-border)]">
        <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">
          Storage for job {jobId.slice(0, 8)}…
        </p>
        <button
          onClick={refresh}
          disabled={loading}
          className="text-[10px] text-indigo-400 hover:text-indigo-300 underline-offset-2 hover:underline disabled:opacity-50"
        >
          {loading ? 'refreshing…' : 'refresh'}
        </button>
      </div>

      {/* 1. Qdrant + HNSW index */}
      <Section
        icon="🔮"
        title="Qdrant — Vector DB (HNSW)"
        accent="indigo"
        summary={`${data.qdrant.vectors} vectors × ${data.qdrant.dimensions}d`}
        onInspect={data.qdrant.vectors > 0 ? () => setInspect('chunks') : undefined}
      >
        <div className="flex justify-between"><span className="text-slate-500">collection</span><span className="font-mono text-indigo-300 text-[11px]">{data.qdrant.collection ?? '(none)'}</span></div>
        <div className="flex justify-between"><span className="text-slate-500">live</span><span className={data.qdrant.live ? 'text-emerald-400' : 'text-slate-500'}>{data.qdrant.live ? '✓ connected' : '— offline'}</span></div>
        <div className="flex justify-between"><span className="text-slate-500">embedding model</span><span className="font-mono text-slate-300 text-[11px]">{data.qdrant.embedding_model}</span></div>

        <div className="mt-1.5 pt-1.5 border-t border-[var(--color-border)] space-y-0.5">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">HNSW index parameters</p>
          <div className="flex justify-between"><span className="text-slate-500">distance metric</span><span className="font-mono text-slate-300 text-[11px]">{data.qdrant.distance}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">connectivity (m)</span><span className="font-mono text-slate-300 text-[11px]">{data.qdrant.hnsw_m} neighbours per node</span></div>
          <div className="flex justify-between"><span className="text-slate-500">build accuracy (ef_construct)</span><span className="font-mono text-slate-300 text-[11px]">{data.qdrant.hnsw_ef_construct}</span></div>
        </div>

        {data.qdrant.sample_vector.length > 0 && (
          <div className="mt-1.5 pt-1.5 border-t border-[var(--color-border)]">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Sample stored vector (first 8 dims)</p>
            <pre className="text-[10px] font-mono text-indigo-300 bg-slate-900/50 rounded px-2 py-1 overflow-x-auto">
              [{data.qdrant.sample_vector.map((x) => x.toFixed(5)).join(', ')}, …]
            </pre>
          </div>
        )}

        <p className="text-[10px] text-slate-500 italic pt-1.5">
          Queried at retrieval time via HNSW search (sub-linear in N). Falls back to in-memory cosine if Qdrant is offline.
        </p>
      </Section>

      {/* 2. SQLite */}
      <Section
        icon="🗃️"
        title="SQLite — Structured tables"
        accent="amber"
        summary={
          data.sqlite.tables.length > 0
            ? `${data.sqlite.tables.length} tables · ${data.sqlite.tables.reduce((sum, t) => sum + t.rows, 0)} rows · ${fmtBytes(data.sqlite.size_bytes)}`
            : 'none'
        }
        onInspect={data.sqlite.tables.length > 0
          ? () => { setSqlInitial(data.sqlite.tables[0].name); setInspect('sql') }
          : undefined}
      >
        {data.sqlite.tables.length === 0 ? (
          <p className="text-slate-500 italic">No structured tables in this document.</p>
        ) : (
          <>
            <div className="flex justify-between text-[11px]"><span className="text-slate-500">file</span><span className="font-mono text-amber-300">{data.sqlite.file}</span></div>
            <div className="mt-1.5 space-y-0.5">
              {data.sqlite.tables.map((t) => (
                <div key={t.name} className="text-[11px]">
                  <span className="font-mono text-amber-400">{t.name}</span>
                  <span className="text-slate-500"> · {t.rows} rows · </span>
                  <span className="text-slate-400 font-mono">[{t.columns.slice(0, 4).join(', ')}{t.columns.length > 4 ? `, +${t.columns.length - 4}` : ''}]</span>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-slate-500 italic pt-1.5">Used for exact numerical queries (SQL-routed questions).</p>
          </>
        )}
      </Section>

      {/* 3. BM25 */}
      <Section
        icon="🔤"
        title="BM25 — Sparse keyword index"
        accent="emerald"
        summary={`${data.bm25.unique_terms.toLocaleString()} terms`}
      >
        <div className="flex justify-between"><span className="text-slate-500">documents indexed</span><span className="font-mono text-slate-300">{data.bm25.doc_count}</span></div>
        <div className="flex justify-between"><span className="text-slate-500">avg doc length</span><span className="font-mono text-slate-300">{data.bm25.avg_doc_len.toFixed(1)} tokens</span></div>
        <p className="text-[10px] text-slate-500 italic pt-1">Used for exact-keyword match (product names, IDs, amounts).</p>
      </Section>

      {/* 4. Knowledge graph */}
      <Section
        icon="🕸️"
        title="Knowledge Graph"
        accent="violet"
        summary={data.kg.nodes > 0 ? `${data.kg.nodes} nodes · ${data.kg.edges} edges` : 'skipped'}
        onInspect={data.kg.nodes > 0 ? () => setInspect('kg') : undefined}
      >
        {data.kg.nodes === 0 ? (
          <p className="text-slate-500 italic">No KG built — either the doc had no substantive prose, or `extract_entities` was skipped.</p>
        ) : (
          <>
            <div className="flex justify-between"><span className="text-slate-500">nodes (entities)</span><span className="font-mono text-violet-300">{data.kg.nodes.toLocaleString()}</span></div>
            <div className="flex justify-between"><span className="text-slate-500">edges (relationships)</span><span className="font-mono text-violet-300">{data.kg.edges.toLocaleString()}</span></div>
            <div className="flex justify-between"><span className="text-slate-500">entity types</span><span className="font-mono text-violet-300">[{data.kg.entity_types.join(', ')}]</span></div>
            <p className="text-[10px] text-slate-500 italic pt-1">Used for entity-anchored questions (&quot;what did &lt;PERSON&gt; say?&quot;).</p>
          </>
        )}
      </Section>

      {/* 5. Disk */}
      <Section
        icon="💾"
        title="Disk — Persistent artifacts"
        accent="slate"
        summary={`${data.disk.file_count} files · ${fmtBytes(data.disk.total_bytes)}`}
      >
        <p className="text-[10px] text-slate-500 font-mono">{data.disk.path}</p>
        <div className="mt-1.5 space-y-0.5 max-h-48 overflow-y-auto">
          {data.disk.files.map((f) => (
            <div key={f.name} className="flex justify-between text-[11px] font-mono">
              <span className="text-slate-400">{f.name}</span>
              <span className="text-slate-500">{fmtBytes(f.size_bytes)}</span>
            </div>
          ))}
        </div>
        <p className="text-[10px] text-slate-500 italic pt-1">All artifacts survive backend restarts — pipeline can resume from any stage.</p>
      </Section>

      {/* 6. In-memory cache */}
      <Section
        icon="⚡"
        title="In-memory cache"
        accent="cyan"
        summary={`${data.cache.key_count} keys hot`}
      >
        <div className="text-[10px] font-mono text-slate-400 leading-relaxed">
          {data.cache.keys.length === 0 ? (
            <span className="italic text-slate-500">(none — will rehydrate from disk on next access)</span>
          ) : (
            data.cache.keys.join(', ')
          )}
        </div>
        <p className="text-[10px] text-slate-500 italic pt-1">Hot cache for sub-second /ask responses; rebuilt from disk on backend restart.</p>
      </Section>

      {/* ── Inspector modals ── */}
      {inspect === 'chunks' && (
        <ChunkInspector jobId={jobId} onClose={() => setInspect(null)} />
      )}
      {inspect === 'sql' && data.sqlite.tables.length > 0 && (
        <SqlInspector
          jobId={jobId}
          tableNames={data.sqlite.tables.map((t) => t.name)}
          initialTable={sqlInitial || data.sqlite.tables[0].name}
          onClose={() => setInspect(null)}
        />
      )}
      {inspect === 'kg' && (
        <KgInspector jobId={jobId} onClose={() => setInspect(null)} />
      )}
    </div>
  )
}
