import { useState } from 'react'
import type { StageState } from '../../hooks/usePipelineStore'

interface Chunk {
  id: string
  text: string
  token_count: number
  page?: number | null
  heading_path?: string | null
}

interface ChunkingPayload {
  strategy?: string
  chunk_count?: number
  avg_chunk_size_tokens?: number
  min_chunk_tokens?: number
  max_chunk_tokens?: number
  overlap_tokens?: number
  total_chunk_tokens?: number
  doc_tokens_est?: number
  coverage_pct?: number
  chunks?: Chunk[]
  size_distribution?: number[]
}

// Roughly convert tokens to words for display
const toWords = (tokens: number) => Math.round(tokens * 0.75)

function ChunkModal({ chunk, onClose }: { chunk: Chunk; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="relative bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl w-full max-w-2xl max-h-[80vh] flex flex-col shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-xs text-slate-500 shrink-0">Chunk {chunk.id}</span>
            {chunk.heading_path && (
              <span className="text-xs text-indigo-400 truncate">under: {chunk.heading_path}</span>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0 ml-2">
            {chunk.page != null && <span className="text-xs text-slate-500">Page {chunk.page}</span>}
            <span className="text-xs px-1.5 py-0.5 rounded bg-indigo-900/30 text-indigo-400">
              ~{toWords(chunk.token_count)} words
            </span>
            <button onClick={onClose} className="text-slate-500 hover:text-white text-lg leading-none ml-1">×</button>
          </div>
        </div>
        <div className="overflow-y-auto p-4">
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">{chunk.text}</p>
        </div>
      </div>
    </div>
  )
}

export function ChunkerViz({ stage }: { stage: StageState }) {
  const p = stage.payload as ChunkingPayload
  const [selected, setSelected] = useState<Chunk | null>(null)

  if (p?.chunk_count == null) return null

  const chunks    = p.chunks ?? []
  const dist      = p.size_distribution ?? []
  const maxBucket = Math.max(...dist, 1)
  const coverage  = p.coverage_pct ?? 0
  const overlap   = p.overlap_tokens ?? 0

  return (
    <>
      <div className="space-y-4">
        {/* Summary */}
        <div className="px-3 py-2.5 rounded-lg bg-indigo-900/20 border border-indigo-700/30 text-xs text-slate-300 leading-relaxed">
          Long documents are split into smaller overlapping pieces called "chunks" — each roughly {toWords(p.avg_chunk_size_tokens ?? 300)} words. Each chunk will be independently searchable. Overlapping ensures no information is lost at the boundaries.
        </div>

        {/* Coverage */}
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">How much of the document is covered?</p>
          <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border ${
            coverage >= 90 ? 'bg-emerald-900/15 border-emerald-800/30' : 'bg-yellow-900/15 border-yellow-800/30'
          }`}>
            <span className={`text-2xl font-bold ${coverage >= 90 ? 'text-emerald-300' : 'text-yellow-300'}`}>
              {coverage.toFixed(0)}%
            </span>
            <div className="text-xs text-slate-400 leading-relaxed">
              {coverage >= 90
                ? 'Excellent — nearly the entire document is captured in chunks.'
                : 'Some content may have been skipped (very short sections or boilerplate).'}
            </div>
          </div>
        </div>

        {/* Stats */}
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">Chunk statistics</p>
          <div className="grid grid-cols-2 gap-1.5">
            <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
              <p className="text-lg font-bold text-white">{p.chunk_count}</p>
              <p className="text-xs text-slate-400">chunks created</p>
            </div>
            <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
              <p className="text-lg font-bold text-white">~{toWords(p.avg_chunk_size_tokens ?? 0)}</p>
              <p className="text-xs text-slate-400">avg words per chunk</p>
            </div>
            <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
              <p className="text-lg font-bold text-white">~{toWords(overlap)}</p>
              <p className="text-xs text-slate-400">words overlap between chunks</p>
            </div>
            <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
              <p className="text-lg font-bold text-white">{toWords(p.min_chunk_tokens ?? 0)}–{toWords(p.max_chunk_tokens ?? 0)}</p>
              <p className="text-xs text-slate-400">word range (min–max)</p>
            </div>
          </div>
        </div>

        {/* Size distribution */}
        {dist.length > 0 && dist.some((v) => v > 0) && (
          <div>
            <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
              Chunk size distribution
            </p>
            <div className="flex items-end gap-0.5 h-12 bg-[var(--color-bg)] rounded-lg px-2 py-1 border border-[var(--color-border)]">
              {dist.map((count, i) => (
                <div key={i} className="flex-1 flex flex-col items-center justify-end" title={`${count} chunks`}>
                  <div className="w-full bg-indigo-500/70 rounded-sm min-h-[2px]" style={{ height: `${(count / maxBucket) * 100}%` }} />
                </div>
              ))}
            </div>
            <div className="flex justify-between text-[10px] text-slate-600 mt-1 px-1">
              <span>shorter (~{toWords(p.min_chunk_tokens ?? 0)} words)</span>
              <span>longer (~{toWords(p.max_chunk_tokens ?? 0)} words)</span>
            </div>
          </div>
        )}

        {/* Chunk list */}
        {chunks.length > 0 && (
          <div>
            <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
              All chunks ({chunks.length}) — click any to read its full text
            </p>
            <div className="space-y-1.5 max-h-48 overflow-y-auto">
              {chunks.map((chunk, i) => (
                <button
                  key={chunk.id}
                  onClick={() => setSelected(chunk)}
                  className="w-full text-left rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-2.5 py-2 hover:border-indigo-500/50 hover:bg-indigo-500/5 transition-all group"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs text-slate-600 w-6 shrink-0">#{i + 1}</span>
                    {chunk.heading_path && (
                      <span className="text-xs text-indigo-400/80 truncate flex-1">{chunk.heading_path}</span>
                    )}
                    <div className="flex items-center gap-1.5 ml-auto shrink-0">
                      {chunk.page != null && <span className="text-xs text-slate-600">p{chunk.page}</span>}
                      <span className="text-xs text-slate-500">~{toWords(chunk.token_count)}w</span>
                      <span className="text-xs text-slate-600 group-hover:text-slate-400">↗</span>
                    </div>
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed line-clamp-2">{chunk.text}</p>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {selected && <ChunkModal chunk={selected} onClose={() => setSelected(null)} />}
    </>
  )
}
