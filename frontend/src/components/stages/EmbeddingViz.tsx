import type { StageState } from '../../hooks/usePipelineStore'

interface EmbeddingPayload {
  model?: string
  vector_dim?: number
  chunks_embedded?: number
  dense_sample?: number[]
  sparse_index_terms?: number
  embedding_ms?: number
  use_real_embeddings?: boolean
  llm_input_tokens?: number
  llm_cost_usd?: number
}

function Tip({ text }: { text: string }) {
  return <p className="text-xs text-slate-500 leading-relaxed">{text}</p>
}

export function EmbeddingViz({ stage }: { stage: StageState }) {
  const p = stage.payload as EmbeddingPayload
  if (!p) return null

  const chunks = p.chunks_embedded ?? 0
  const terms = p.sparse_index_terms ?? 0
  const ms = p.embedding_ms ?? 0
  const cost = p.llm_cost_usd ?? 0
  const isMock = !p.use_real_embeddings

  return (
    <div className="space-y-4">

      {/* Plain-English summary */}
      <div className="px-3 py-2.5 rounded-lg bg-indigo-900/20 border border-indigo-700/30 text-xs text-slate-300 leading-relaxed">
        Each chunk of your document was converted into a list of {(p.vector_dim ?? 1536).toLocaleString()} numbers
        (a "vector") that captures its <span className="text-indigo-300 font-medium">meaning</span>.
        At search time, a query is converted the same way and the closest vectors are returned — even if the query uses different words than the document.
      </div>

      {/* What was processed */}
      <div>
        <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">What was processed</p>
        <div className="grid grid-cols-2 gap-1.5">
          <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
            <p className="text-lg font-bold text-white">{chunks}</p>
            <p className="text-xs text-slate-400">chunks vectorized</p>
            <p className="text-[10px] text-slate-600 mt-0.5">one vector per chunk</p>
          </div>
          <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
            <p className="text-lg font-bold text-white">{(p.vector_dim ?? 1536).toLocaleString()}</p>
            <p className="text-xs text-slate-400">dimensions per vector</p>
            <p className="text-[10px] text-slate-600 mt-0.5">richer = more accurate</p>
          </div>
        </div>
      </div>

      {/* Search methods */}
      <div>
        <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">Search methods enabled</p>
        <div className="space-y-1.5">
          <div className="flex items-start gap-2.5 px-3 py-2 rounded-lg bg-indigo-900/15 border border-indigo-800/30">
            <span className="text-indigo-400 mt-0.5">⬡</span>
            <div>
              <p className="text-xs font-medium text-indigo-300">Semantic (AI vectors)</p>
              <p className="text-[11px] text-slate-500 mt-0.5">Finds relevant chunks even when different words are used — understands meaning, not just keywords</p>
            </div>
          </div>
          <div className="flex items-start gap-2.5 px-3 py-2 rounded-lg bg-emerald-900/15 border border-emerald-800/30">
            <span className="text-emerald-400 mt-0.5">≡</span>
            <div>
              <p className="text-xs font-medium text-emerald-300">Keyword (BM25) — {terms.toLocaleString()} unique terms</p>
              <p className="text-[11px] text-slate-500 mt-0.5">Classic full-text search across all words in the document — fast and precise for exact matches</p>
            </div>
          </div>
          <div className="flex items-start gap-2.5 px-3 py-2 rounded-lg bg-amber-900/15 border border-amber-800/30">
            <span className="text-amber-400 mt-0.5">⇄</span>
            <div>
              <p className="text-xs font-medium text-amber-300">Combined (RRF fusion)</p>
              <p className="text-[11px] text-slate-500 mt-0.5">Both rankings are merged — results that score well in both methods are boosted to the top</p>
            </div>
          </div>
        </div>
      </div>

      {/* Cost / performance */}
      <div>
        <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">Performance</p>
        <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] divide-y divide-[var(--color-border)]">
          <div className="flex items-center px-2.5 py-1.5 text-xs">
            <span className="text-slate-500 flex-1">Processing time</span>
            <span className="font-mono text-white">{ms.toFixed(0)}ms</span>
          </div>
          <div className="flex items-center px-2.5 py-1.5 text-xs">
            <span className="text-slate-500 flex-1">Model</span>
            <span className="font-mono text-slate-300">
              {isMock ? 'mock (no OpenAI key)' : 'text-embedding-3-large'}
            </span>
          </div>
          {!isMock && cost > 0 && (
            <div className="flex items-center px-2.5 py-1.5 text-xs">
              <span className="text-slate-500 flex-1">OpenAI cost</span>
              <span className="font-mono text-emerald-400">${cost.toFixed(6)}</span>
            </div>
          )}
          {isMock && (
            <div className="flex items-center px-2.5 py-1.5 text-xs">
              <span className="text-slate-500 flex-1">Note</span>
              <span className="text-yellow-400">Set OPENAI_API_KEY for real vectors</span>
            </div>
          )}
        </div>
      </div>

    </div>
  )
}
