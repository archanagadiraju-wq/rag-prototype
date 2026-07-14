import { useMemo } from 'react'
import { usePipelineStore } from '../../hooks/usePipelineStore'
import type { StageEvent } from '../../types/events'

// Translate a completed stage event into a one-line plain-English summary
function summarise(e: StageEvent): string {
  const p = e.payload as Record<string, unknown>
  if (!p) return ''

  switch (e.stage_id) {
    case 1: // Intake
      if (p.filename) return `"${p.filename}" received · ${p.size_bytes ? formatBytes(p.size_bytes as number) : ''}`
      break
    case 2: // Format Detection
      if (p.sub_structure) {
        const sub = String(p.sub_structure).replace(/-/g, ' ')
        return `Identified as ${sub} · language: ${p.language ?? 'unknown'}`
      }
      break
    case 3: // Format Parser
      return [
        p.word_count ? `${Number(p.word_count).toLocaleString()} words extracted` : '',
        p.table_count ? `${p.table_count} tables` : '',
        p.image_count ? `${p.image_count} images` : '',
        p.page_count  ? `${p.page_count} pages` : '',
      ].filter(Boolean).join(' · ')
    case 4: // Content Intelligence
      if (p.doc_type) {
        return `Classified as ${String(p.doc_type).replace('_', ' ')} (${p.domain ?? 'general'})`
      }
      break
    case 5: // Chunking
      if (p.chunk_count != null) {
        const avg = p.avg_chunk_size_tokens ? ` · avg ~${Math.round(Number(p.avg_chunk_size_tokens) * 0.75)} words each` : ''
        const cov = p.coverage_pct != null ? ` · ${Number(p.coverage_pct).toFixed(0)}% of document covered` : ''
        return `Split into ${p.chunk_count} searchable pieces${avg}${cov}`
      }
      break
    case 6: // Multi-Modal
      if ((p.tables_serialised as number) > 0 || (p.images_captioned as number) > 0) {
        return [
          (p.tables_serialised as number) > 0 ? `${p.tables_serialised} tables described by AI` : '',
          (p.images_captioned as number) > 0  ? `${p.images_captioned} images captioned` : '',
        ].filter(Boolean).join(' · ')
      }
      return 'No tables or images in this document — skipped'
    case 7: // Embedding
      if (p.chunks_embedded != null) {
        const real = p.use_real_embeddings ? 'OpenAI vectors' : 'mock vectors'
        return `${p.chunks_embedded} chunks → ${Number(p.vector_dim ?? 1536).toLocaleString()}-dim ${real} · ${(p.sparse_index_terms as number)?.toLocaleString()} keywords indexed`
      }
      break
    case 8: // Metadata
      if (p.total_metadata_keys != null) {
        return `Each chunk tagged with ${p.total_metadata_keys} metadata fields (doc type, page, section, etc.)`
      }
      break
    case 9: // Knowledge Graph
      if (p.entity_count != null) {
        const ents = Number(p.entity_count)
        const rels = Number(p.relationship_count ?? 0)
        return ents > 0
          ? `${ents} entities · ${rels} connections mapped across ${p.chunk_count} chunks`
          : `No named entities found — graph built with structure only`
      }
      break
    case 10: // Vector Store
      if (p.vectors_upserted != null) {
        const live = p.qdrant_live ? 'saved to Qdrant' : 'held in memory (Qdrant offline)'
        return `${p.vectors_upserted} vectors ${live}`
      }
      break
    case 11: // RAG Ready
      if (p.routing_summary != null) {
        const s = p.routing_summary as Record<string, unknown>
        const total = Number(s.total_questions ?? 0)
        const vec   = Number(s.vector_count ?? 0)
        const sql   = Number(s.sql_count ?? 0)
        const kg    = Number(s.kg_count ?? 0)
        const hyb   = Number(s.hybrid_count ?? 0)
        const parts = [
          vec  > 0 ? `${vec} vector` : '',
          kg   > 0 ? `${kg} graph`  : '',
          sql  > 0 ? `${sql} SQL`   : '',
          hyb  > 0 ? `${hyb} hybrid`: '',
        ].filter(Boolean).join(' · ')
        return `${total} questions across ${parts} — pipeline ready`
      }
      if (p.retrieval_results) {
        const results = (p.retrieval_results as unknown[]).length
        const ms = p.total_retrieval_ms ? `${Number(p.total_retrieval_ms).toFixed(0)}ms` : ''
        return `Test search returned ${results} relevant chunks${ms ? ' in ' + ms : ''}`
      }
      break
    case 12: // LLM Answer (Custom pipeline)
      if (p.answers != null) {
        const count = (p.answers as unknown[]).length
        const totalTok = Number(p.total_tokens ?? 0)
        const ms = p.total_llm_ms ? `${Number(p.total_llm_ms).toFixed(0)}ms` : ''
        const cost = p.total_cost_usd ? ` · $${Number(p.total_cost_usd).toFixed(4)}` : ''
        return `${count} questions answered · ${totalTok.toLocaleString()} tokens${ms ? ' · ' + ms : ''}${cost}`
      }
      break
    default:
      // Handle Docling LLM Answer (stage_id 9) — detected by payload shape
      if (p.answers != null && Array.isArray(p.answers)) {
        const count = (p.answers as unknown[]).length
        const totalTok = Number(p.total_tokens ?? 0)
        const ms = p.total_llm_ms ? `${Number(p.total_llm_ms).toFixed(0)}ms` : ''
        return `${count} questions answered · ${totalTok.toLocaleString()} tokens${ms ? ' · ' + ms : ''}`
      }
      if (e.stage_name && p.chunk_count) return `${e.stage_name} complete`
  }
  return ''
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(2)} MB`
}

function formatTime(ms: number): string {
  return ms < 1000 ? `${ms.toFixed(0)}ms` : `${(ms / 1000).toFixed(2)}s`
}

const STAGE_DESC: Record<number, string> = {
  1:  'Document received and fingerprinted',
  2:  'File type and structure identified',
  3:  'Text, tables, and images extracted',
  4:  'Document classified and summarised by AI',
  5:  'Document split into searchable chunks',
  6:  'Tables and images converted to text',
  7:  'Chunks converted to AI vectors for semantic search',
  8:  'Each chunk tagged with metadata for filtering',
  9:  'Named entities extracted and wired into a knowledge graph',
  10: 'Vectors saved to search database',
  11: 'Search tested with dense + sparse + graph hybrid retrieval',
  12: 'Retrieval queries answered end-to-end with Claude',
}

export function AuditLog() {
  const wsLog = usePipelineStore((s) => s.wsLog)

  const completed = wsLog.filter((e) => e.status === 'completed' || e.status === 'error')
  const running   = wsLog.filter((e) => e.status === 'started' || e.status === 'running')
  const visibleEntries = useMemo(() => {
    const active = [...running].reverse().slice(0, 6)
    const done = [...completed].reverse().slice(0, 80)
    return [...active, ...done]
  }, [running, completed])

  return (
    <div className="h-full flex flex-col border border-[var(--color-border)] rounded-xl bg-[var(--color-surface)] overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between flex-shrink-0">
        <div>
          <h2 className="text-sm font-semibold text-white">Pipeline Audit Log</h2>
          <p className="text-xs text-slate-500 mt-0.5">A record of every step taken to process your document</p>
        </div>
        <span className="text-xs text-slate-600 font-mono">{wsLog.length} events · latest {Math.min(wsLog.length, 86)} shown</span>
      </div>

      {/* Log entries */}
      <div className="flex-1 overflow-y-auto p-3 space-y-1.5">
        {wsLog.length === 0 && (
          <div className="flex items-center justify-center h-full text-slate-600 text-sm">
            Upload a document to see the audit log
          </div>
        )}

        {visibleEntries.length > 0 && wsLog.length > visibleEntries.length && (
          <div className="rounded-lg border border-slate-800/70 bg-slate-900/50 px-3 py-2 text-[11px] text-slate-400">
            Showing the latest {visibleEntries.length} events to keep the audit view responsive.
          </div>
        )}

        {/* Show active (in-progress) stages at the top */}
        {visibleEntries.filter((e) => e.status === 'started' || e.status === 'running').map((e, i) => (
          <div key={`active-${i}`}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-indigo-900/20 border border-indigo-700/30 animate-pulse"
          >
            <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-xs text-indigo-300 font-medium">
                Stage {e.stage_id} — {e.stage_name}
              </p>
              <p className="text-[11px] text-slate-500 mt-0.5">Running…</p>
            </div>
          </div>
        ))}

        {/* Completed stages, most recent first */}
        {visibleEntries.filter((e) => e.status === 'completed' || e.status === 'error').map((e, i) => {
          const isError = e.status === 'error'
          const summary = isError
            ? String((e.payload as Record<string, unknown>)?.error ?? 'Unknown error')
            : summarise(e)

          return (
            <div
              key={i}
              className={`flex items-start gap-3 px-3 py-2.5 rounded-lg border transition-colors ${
                isError
                  ? 'bg-red-900/15 border-red-800/30'
                  : 'bg-[var(--color-bg)] border-[var(--color-border)] hover:border-slate-600'
              }`}
            >
              {/* Status dot */}
              <div className={`w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 ${
                isError ? 'bg-red-400' : 'bg-emerald-400'
              }`} />

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className={`text-xs font-semibold ${isError ? 'text-red-300' : 'text-white'}`}>
                    Stage {e.stage_id} — {e.stage_name}
                  </span>
                  {e.duration_ms != null && (
                    <span className="text-[10px] text-slate-600 font-mono">{formatTime(e.duration_ms)}</span>
                  )}
                </div>

                {/* What the stage does */}
                {STAGE_DESC[e.stage_id] && !isError && (
                  <p className="text-[11px] text-slate-500 mt-0.5">{STAGE_DESC[e.stage_id]}</p>
                )}

                {/* Outcome summary */}
                {summary && (
                  <p className={`text-xs mt-1 leading-relaxed ${isError ? 'text-red-400' : 'text-slate-300'}`}>
                    {isError ? '✗ ' : '→ '}{summary}
                  </p>
                )}

                {/* L1 pass rate inline */}
                {e.verification && !isError && (
                  <div className="flex items-center gap-1.5 mt-1.5">
                    <div className="flex gap-0.5">
                      {e.verification.l1_checks.map((c, ci) => (
                        <div
                          key={ci}
                          title={`${c.name.replace(/_/g,' ')}: ${c.detail}`}
                          className={`w-2 h-2 rounded-full ${
                            c.passed ? 'bg-emerald-500' : c.severity === 'warn' ? 'bg-yellow-500' : 'bg-red-500'
                          }`}
                        />
                      ))}
                    </div>
                    <span className="text-[10px] text-slate-600">
                      {e.verification.l1_checks.filter(c => c.passed).length}/{e.verification.l1_checks.length} checks passed
                    </span>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
