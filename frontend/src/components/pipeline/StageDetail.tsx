import { usePipelineStore } from '../../hooks/usePipelineStore'
import { IntakeViz } from '../stages/IntakeViz'
import { FormatDetectViz } from '../stages/FormatDetectViz'
import { ParserViz } from '../stages/ParserViz'
import { ContentIntelViz } from '../stages/ContentIntelViz'
import { ChunkerViz } from '../stages/ChunkerViz'
import { MultiModalViz } from '../stages/MultiModalViz'
import { EmbeddingViz } from '../stages/EmbeddingViz'
import { MetadataViz } from '../stages/MetadataViz'
import { KnowledgeGraphViz } from '../stages/KnowledgeGraphViz'
import { VectorStoreViz } from '../stages/VectorStoreViz'
import { RAGReadyViz } from '../stages/RAGReadyViz'
import { LLMAnswerViz } from '../stages/LLMAnswerViz'
import { AgentTurnViz } from '../stages/AgentTurnViz'
import type { StageState } from '../../hooks/usePipelineStore'

export function RichViz({ stage }: { stage: StageState }) {
  if (stage.status !== 'completed') return null

  // Dispatch by stage NAME — works for both pipelines, since stage IDs differ
  // between Mode A (11 stages) and Mode B (8 stages with stage 2 = Docling
  // unified parse that collapses Mode A's stages 2–5).
  const name = stage.name.toLowerCase()

  // Agent stages get a dedicated viz showing input context, reasoning, per-turn
  // metrics, and tool I/O — same shape as /tmp/agent_trace.py CLI output.
  // Checked FIRST so "agent.embed_and_index" doesn't fall through to EmbeddingViz.
  if (name.startsWith('agent.') || name === 'agent finished') {
    return <AgentTurnViz stage={stage} />
  }

  // Shared stages (same name in both pipelines)
  if (name === 'intake')                                       return <IntakeViz stage={stage} />
  if (name.includes('multi-modal') || name.includes('multimodal')) return <MultiModalViz stage={stage} />
  if (name.includes('embedding'))                              return <EmbeddingViz stage={stage} />
  if (name.includes('metadata'))                               return <MetadataViz stage={stage} />
  if (name.includes('knowledge graph'))                        return <KnowledgeGraphViz stage={stage} />
  if (name.includes('vector store'))                           return <VectorStoreViz stage={stage} />
  if (name.includes('rag ready'))                              return <RAGReadyViz stage={stage} />
  if (name.includes('llm answer'))                             return <LLMAnswerViz stage={stage} />

  // Mode A only
  if (name.includes('format detection'))                       return <FormatDetectViz stage={stage} />
  if (name.includes('parser'))                                 return <ParserViz stage={stage} />
  if (name.includes('content intel'))                          return <ContentIntelViz stage={stage} />
  if (name.includes('chunk'))                                  return <ChunkerViz stage={stage} />

  // Mode B only — Docling unified parse collapses format-detect + parser +
  // content-intel + chunker, so render BOTH vizes stacked: content-intel
  // (doc_type, summary, entities) then the chunker (chunk list + distribution).
  if (name.includes('docling') || name.includes('unified parse')) {
    return (
      <div className="space-y-6">
        <ContentIntelViz stage={stage} />
        <div className="pt-2 border-t border-[var(--color-border)]">
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-3">
            Chunks produced by Docling
          </p>
          <ChunkerViz stage={stage} />
        </div>
      </div>
    )
  }

  return null
}

export function StageDetail() {
  const { stages, selectedStage } = usePipelineStore()
  const stage = stages.find((s) => s.id === selectedStage)

  if (!stage || stage.status === 'idle') {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-600 text-sm">
        Click a stage to inspect its payload
      </div>
    )
  }

  const v = stage.verification
  const isAgentStage = stage.name.toLowerCase().startsWith('agent.') || stage.name.toLowerCase() === 'agent finished'
  const hasRichViz = stage.status === 'completed' && (isAgentStage || stage.id <= 12)

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-white">
          Stage {stage.id} — {stage.name}
        </h3>
        {stage.duration_ms != null && (
          <span className="text-xs text-slate-500">{stage.duration_ms.toFixed(0)}ms</span>
        )}
      </div>

      {/* Rich viz */}
      <RichViz stage={stage} />

      {/* Raw payload fallback (only for stages without rich viz, or while running) */}
      {(!hasRichViz || stage.status !== 'completed') && stage.payload && (
        <section>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">Payload</p>
          <pre className="text-xs bg-[var(--color-bg)] rounded-lg p-3 overflow-x-auto text-slate-300 max-h-64 border border-[var(--color-border)]">
            {JSON.stringify(stage.payload, null, 2)}
          </pre>
        </section>
      )}

      {/* Verification */}
      {v && (
        <section>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
            Verification checks
          </p>
          <div className="space-y-1.5">
            {v.l1_checks.map((c, i) => (
              <div
                key={i}
                className={`flex items-start gap-2 text-xs px-2 py-1.5 rounded-lg ${
                  c.passed
                    ? 'bg-emerald-900/20 text-emerald-300'
                    : c.severity === 'warn'
                    ? 'bg-yellow-900/20 text-yellow-300'
                    : 'bg-red-900/20 text-red-300'
                }`}
              >
                <span className="font-mono mt-0.5">{c.passed ? '✓' : c.severity === 'warn' ? '△' : '✗'}</span>
                <div>
                  <span className="font-medium">{c.name.replace(/_/g, ' ')}</span>
                  {c.detail && <span className="opacity-70 ml-2">{c.detail}</span>}
                </div>
              </div>
            ))}
            {v.l2_score != null && (
              <div className="px-2 py-1.5 rounded-lg bg-indigo-900/20 text-indigo-300 text-xs">
                <span className="font-medium">L2 Semantic Score:</span>
                <span className="ml-2 font-mono">{v.l2_score.toFixed(3)}</span>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
