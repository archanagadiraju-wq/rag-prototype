import type { StageState } from '../../hooks/usePipelineStore'

interface KGPayload {
  entity_count?: number
  relationship_count?: number
  unique_entity_types?: string[]
  top_entities?: { key: string; text: string; label: string; mentions: number }[]
  chunk_count?: number
  graph_nodes?: number
  build_ms?: number
}

const TYPE_COLOR: Record<string, { bg: string; text: string; label: string }> = {
  PERSON:      { bg: 'bg-violet-500/20', text: 'text-violet-300', label: 'Person' },
  ORG:         { bg: 'bg-indigo-500/20', text: 'text-indigo-300', label: 'Organisation' },
  GPE:         { bg: 'bg-emerald-500/20', text: 'text-emerald-300', label: 'Place' },
  PRODUCT:     { bg: 'bg-amber-500/20',  text: 'text-amber-300',  label: 'Product' },
  EVENT:       { bg: 'bg-rose-500/20',   text: 'text-rose-300',   label: 'Event' },
  LAW:         { bg: 'bg-slate-500/20',  text: 'text-slate-300',  label: 'Law / Regulation' },
  WORK_OF_ART: { bg: 'bg-pink-500/20',   text: 'text-pink-300',   label: 'Work of Art' },
  FAC:         { bg: 'bg-cyan-500/20',   text: 'text-cyan-300',   label: 'Facility' },
  NORP:        { bg: 'bg-orange-500/20', text: 'text-orange-300', label: 'Nationality / Group' },
}

function EntityChip({ entity }: { entity: NonNullable<KGPayload['top_entities']>[0] }) {
  const style = TYPE_COLOR[entity.label] ?? { bg: 'bg-slate-700/40', text: 'text-slate-300', label: entity.label }
  return (
    <div className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border border-slate-700/40 ${style.bg}`}>
      <span className={`text-[9px] font-bold uppercase tracking-wider ${style.text} w-14 shrink-0`}>
        {style.label}
      </span>
      <span className="text-xs text-slate-200 flex-1 truncate">{entity.text}</span>
      <span className="text-[10px] text-slate-500 font-mono shrink-0">{entity.mentions}×</span>
    </div>
  )
}

export function KnowledgeGraphViz({ stage }: { stage: StageState }) {
  const p = stage.payload as KGPayload
  if (!p) return null

  const entities = p.top_entities ?? []
  const types = p.unique_entity_types ?? []
  const hasGraph = (p.entity_count ?? 0) > 0

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="px-3 py-2.5 rounded-lg bg-indigo-900/20 border border-indigo-700/30 text-xs text-slate-300 leading-relaxed">
        Every chunk was scanned for named entities — people, organisations, places, products, and more.
        These are wired into a graph where chunks and entities are connected by mention links.
        When you search, the retrieval engine uses this graph to surface related chunks that share key entities with the top results.
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-1.5">
        <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2 text-center">
          <p className="text-lg font-bold text-white">{(p.graph_nodes ?? 0).toLocaleString()}</p>
          <p className="text-[10px] text-slate-500 mt-0.5">graph nodes</p>
        </div>
        <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2 text-center">
          <p className="text-lg font-bold text-white">{(p.relationship_count ?? 0).toLocaleString()}</p>
          <p className="text-[10px] text-slate-500 mt-0.5">connections</p>
        </div>
        <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2 text-center">
          <p className="text-lg font-bold text-white">{p.build_ms != null ? `${p.build_ms.toFixed(0)}ms` : '—'}</p>
          <p className="text-[10px] text-slate-500 mt-0.5">to build</p>
        </div>
      </div>

      {/* Entity types legend */}
      {types.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">Entity types found</p>
          <div className="flex flex-wrap gap-1.5">
            {types.map((t) => {
              const style = TYPE_COLOR[t] ?? { bg: 'bg-slate-700/40', text: 'text-slate-300', label: t }
              return (
                <span key={t} className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${style.bg} ${style.text}`}>
                  {style.label}
                </span>
              )
            })}
          </div>
        </div>
      )}

      {/* Top entities */}
      {entities.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
            Most-mentioned entities
          </p>
          <div className="space-y-1">
            {entities.map((e) => <EntityChip key={e.key} entity={e} />)}
          </div>
        </div>
      )}

      {!hasGraph && (
        <div className="px-3 py-3 rounded-lg bg-yellow-900/15 border border-yellow-800/30 text-xs text-yellow-300">
          No named entities were detected in this document. The pipeline will still work — retrieval falls back to dense + BM25 only.
        </div>
      )}

      {/* How it helps */}
      <div className="px-2.5 py-2 rounded-lg bg-slate-800/30 border border-slate-700/30 text-[10px] text-slate-600 leading-relaxed space-y-1">
        <p><span className="text-slate-400">How this improves search:</span> when the top-ranked chunks mention "Dr. Smith" and "clinical trial", any other chunk also mentioning those gets a graph bonus score — even if it uses different words.</p>
        <p><span className="text-slate-400">Co-occurrence edges:</span> entities appearing together in the same chunk are directly linked, capturing relationships the text implies but doesn't state explicitly.</p>
      </div>
    </div>
  )
}
