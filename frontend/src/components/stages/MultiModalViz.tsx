import { useState } from 'react'
import type { StageState } from '../../hooks/usePipelineStore'

interface EnrichedTable {
  id?: string
  description?: string
  as_markdown?: string
  headers?: string[]
  rows?: string[][]
}

interface Caption {
  id?: string
  caption?: string
  page?: number | null
  width?: number
  height?: number
}

interface OcrChunk {
  id?: string
  text?: string
  page?: number | null
}

interface MultiModalPayload {
  images_captioned?: number
  tables_serialised?: number
  tables_enriched?: EnrichedTable[]
  captions?: Caption[]
  ocr_chunks?: OcrChunk[]
  ocr_pages_count?: number
  model_used?: string
  llm_input_tokens?: number
  llm_output_tokens?: number
  llm_cost_usd?: number
}

function TableModal({ table, onClose }: { table: EnrichedTable; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl w-full max-w-3xl max-h-[80vh] flex flex-col shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
          <span className="text-xs text-slate-400 font-mono">{table.id}</span>
          <button onClick={onClose} className="text-slate-500 hover:text-white text-lg leading-none">×</button>
        </div>
        {table.description && (
          <div className="px-4 py-2 border-b border-[var(--color-border)] bg-indigo-900/10">
            <p className="text-xs text-slate-400 font-medium mb-0.5">AI description</p>
            <p className="text-xs text-indigo-300 italic">{table.description}</p>
          </div>
        )}
        <div className="overflow-auto p-4">
          <pre className="text-xs text-slate-300 font-mono leading-relaxed whitespace-pre-wrap">
            {table.as_markdown || '(no content)'}
          </pre>
        </div>
      </div>
    </div>
  )
}

function OcrCard({ chunk }: { chunk: OcrChunk }) {
  const [open, setOpen] = useState(false)
  const preview = (chunk.text ?? '').slice(0, 160).replace(/\n+/g, ' ')
  return (
    <div className="rounded-lg border border-amber-700/30 bg-amber-900/10">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full text-left px-2.5 py-2 flex items-center gap-2"
      >
        <span className="text-[10px] font-semibold uppercase tracking-widest text-amber-500 bg-amber-900/30 px-1.5 py-0.5 rounded">
          OCR
        </span>
        <span className="text-xs text-slate-500 font-mono">{chunk.id ?? 'page'}</span>
        {chunk.page != null && (
          <span className="text-xs text-slate-600">· page {chunk.page}</span>
        )}
        <span className="ml-auto text-slate-600 text-xs">{open ? '▲' : '▼'}</span>
      </button>
      {!open && (
        <p className="px-2.5 pb-2 text-xs text-slate-400 italic line-clamp-2">
          "{preview}{(chunk.text ?? '').length > 160 ? '…' : ''}"
        </p>
      )}
      {open && (
        <pre className="px-2.5 pb-3 text-xs text-slate-300 leading-relaxed whitespace-pre-wrap font-mono border-t border-amber-700/20 pt-2 mx-2.5">
          {chunk.text}
        </pre>
      )}
    </div>
  )
}

export function MultiModalViz({ stage }: { stage: StageState }) {
  const p = stage.payload as MultiModalPayload
  const [selectedTable, setSelectedTable] = useState<EnrichedTable | null>(null)

  if (!p) return null

  const tables     = p.tables_enriched ?? []
  const captions   = p.captions ?? []
  const ocrChunks  = p.ocr_chunks ?? []
  const ocrCount   = p.ocr_pages_count ?? ocrChunks.length
  const hasWork    = (p.tables_serialised ?? 0) > 0 || (p.images_captioned ?? 0) > 0 || ocrCount > 0

  // stat grid: 2 cols normally, 3 when OCR is present
  const statCols = ocrCount > 0 ? 'grid-cols-3' : 'grid-cols-2'

  return (
    <>
      <div className="space-y-4">
        {/* Summary */}
        <div className="px-3 py-2.5 rounded-lg bg-indigo-900/20 border border-indigo-700/30 text-xs text-slate-300 leading-relaxed">
          Tables and images can't be searched as raw data. This stage converts them into searchable text —
          tables get AI-generated descriptions, images get captions, and scanned pages are OCR'd via Claude vision.
        </div>

        {!hasWork ? (
          <div className="px-3 py-3 rounded-lg bg-slate-800/40 border border-slate-700/40 text-xs text-slate-500 text-center">
            No tables or images found in this document — stage skipped.
          </div>
        ) : (
          <>
            {/* Stats */}
            <div className={`grid ${statCols} gap-1.5`}>
              <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
                <p className="text-lg font-bold text-white">{p.tables_serialised ?? 0}</p>
                <p className="text-xs text-slate-400">tables converted</p>
              </div>
              <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
                <p className="text-lg font-bold text-white">{p.images_captioned ?? 0}</p>
                <p className="text-xs text-slate-400">images captioned</p>
              </div>
              {ocrCount > 0 && (
                <div className="rounded-lg bg-amber-900/20 border border-amber-700/30 px-2.5 py-2">
                  <p className="text-lg font-bold text-amber-400">{ocrCount}</p>
                  <p className="text-xs text-amber-600">pages OCR'd</p>
                </div>
              )}
            </div>

            {/* AI cost */}
            {p.model_used && (
              <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700/50 text-xs">
                <span className="text-slate-500">Claude AI</span>
                <span className="text-slate-500">·</span>
                <span className="text-slate-300">{(p.llm_input_tokens ?? 0).toLocaleString()} tokens in</span>
                <span className="text-slate-500">·</span>
                <span className="text-slate-300">{(p.llm_output_tokens ?? 0).toLocaleString()} out</span>
                <span className="ml-auto text-emerald-400 font-mono">${((p.llm_cost_usd ?? 0) * 100).toFixed(4)}¢</span>
              </div>
            )}
          </>
        )}

        {/* Enriched tables */}
        {tables.length > 0 && (
          <div>
            <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
              Tables with AI descriptions — click to view
            </p>
            <div className="space-y-1.5">
              {tables.map((tbl, i) => (
                <button
                  key={tbl.id ?? i}
                  onClick={() => setSelectedTable(tbl)}
                  className="w-full text-left rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-2.5 py-2 hover:border-indigo-500/50 hover:bg-indigo-500/5 transition-all group"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs text-slate-600 font-mono shrink-0">{tbl.id ?? `Table ${i + 1}`}</span>
                    <span className="text-xs text-slate-600 group-hover:text-slate-400 ml-auto">view ↗</span>
                  </div>
                  {tbl.description && (
                    <p className="text-xs text-indigo-300/80 italic leading-relaxed line-clamp-2">{tbl.description}</p>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Image captions */}
        {captions.length > 0 && (
          <div>
            <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
              Image captions
            </p>
            <div className="space-y-1.5">
              {captions.map((cap, i) => (
                <div key={cap.id ?? i} className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-2.5 py-2">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs text-slate-600 font-mono">{cap.id ?? `Image ${i + 1}`}</span>
                    {cap.page != null && <span className="text-xs text-slate-600">· page {cap.page}</span>}
                    {cap.width && cap.height && (
                      <span className="text-xs text-slate-600 ml-auto">{cap.width}×{cap.height}px</span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 italic leading-relaxed">"{cap.caption}"</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Vision OCR results */}
        {ocrChunks.length > 0 && (
          <div>
            <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
              Scanned pages — text recovered via Claude vision
            </p>
            <div className="space-y-1.5">
              {ocrChunks.map((chunk, i) => (
                <OcrCard key={chunk.id ?? i} chunk={chunk} />
              ))}
            </div>
          </div>
        )}
      </div>

      {selectedTable && <TableModal table={selectedTable} onClose={() => setSelectedTable(null)} />}
    </>
  )
}
