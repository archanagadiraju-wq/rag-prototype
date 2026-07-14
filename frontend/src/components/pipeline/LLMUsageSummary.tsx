import { usePipelineStore } from '../../hooks/usePipelineStore'

function fmtMs(ms: number): string {
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`
  if (ms >= 1_000)  return `${(ms / 1_000).toFixed(2)}s`
  return `${ms.toFixed(0)}ms`
}

// Read tokens / cost from a stage's payload, handling both Mode A/B shape
// (top-level llm_*) and agent shape (nested under `turn`). For agent stages
// whose tool produced OpenAI embeddings, also add the embedding cost — keeps
// this view consistent with the JobSummary endpoint's combined total.
function stageMetrics(s: { payload?: Record<string, unknown> }): {
  inTokens: number; outTokens: number; cost: number;
} {
  const p = s.payload ?? {}
  const turn = (p.turn as Record<string, unknown>) ?? {}
  const toolResult = (p.tool_result as Record<string, unknown>) ?? {}

  // Mode A/B stages — top-level llm_* fields
  const fromTopLevel = {
    inTokens:  (p.llm_input_tokens  as number) ?? 0,
    outTokens: (p.llm_output_tokens as number) ?? 0,
    cost:      (p.llm_cost_usd      as number) ?? 0,
  }

  // Agent stages — turn metrics for the AGENT's Claude call + any extra
  // API calls made BY the tool itself:
  //   • describe_tables tool → Claude table-description call (llm_*_tokens)
  //   • embed_and_index tool → OpenAI embedding call (embedding_cost_usd)
  // Both must be added so the per-stage sum equals true Anthropic+OpenAI spend.
  const turnAnthropicCost  = (turn.turn_cost_usd          as number) ?? 0
  const toolAnthropicCost  = (toolResult.llm_cost_usd     as number) ?? 0
  const toolAnthropicIn    = (toolResult.llm_input_tokens  as number) ?? 0
  const toolAnthropicOut   = (toolResult.llm_output_tokens as number) ?? 0
  const toolOpenAICost     = (toolResult.embedding_cost_usd as number) ?? 0
  const fromTurn = {
    inTokens:  ((turn.turn_input_tokens  as number) ?? 0) + toolAnthropicIn,
    outTokens: ((turn.turn_output_tokens as number) ?? 0) + toolAnthropicOut,
    cost:      turnAnthropicCost + toolAnthropicCost + toolOpenAICost,
  }

  // Prefer turn fields when present (agent stages); otherwise top-level (Mode A/B).
  // For agent stages with shared turn metrics (second tool of a multi-tool turn),
  // turn_input_tokens is 0 — we still may have OpenAI cost from tool_result, so
  // bias toward fromTurn whenever ANY turn data exists.
  return turn && Object.keys(turn).length > 0 ? fromTurn : fromTopLevel
}


export function LLMUsageSummary() {
  const stages = usePipelineStore((s) => s.stages)

  const completedStages = stages.filter((s) => s.status === 'completed')
  const llmStages       = completedStages.filter((s) => {
    const m = stageMetrics(s)
    return m.inTokens > 0 || m.outTokens > 0
  })

  if (completedStages.length === 0) return null

  const totalIn   = llmStages.reduce((sum, s) => sum + stageMetrics(s).inTokens,  0)
  const totalOut  = llmStages.reduce((sum, s) => sum + stageMetrics(s).outTokens, 0)
  const totalCost = llmStages.reduce((sum, s) => sum + stageMetrics(s).cost,      0)
  const totalMs   = completedStages.reduce((sum, s) => sum + (s.duration_ms ?? 0), 0)

  return (
    <div className="border border-[var(--color-border)] rounded-xl bg-[var(--color-surface)] overflow-hidden">
      <div className="px-3 py-2 border-b border-[var(--color-border)] text-xs text-slate-500 font-medium">
        Pipeline Summary
      </div>

      <div className="divide-y divide-[var(--color-border)]">
        {/* Per-stage LLM rows */}
        {llmStages.map((s) => {
          const m = stageMetrics(s)
          return (
            <div key={s.id} className="flex items-center gap-2 px-3 py-1.5 text-xs font-mono">
              <span className="text-slate-600 w-4">{s.id}.</span>
              <span className="text-slate-400 flex-1 truncate">{s.name}</span>
              <span className="text-slate-500">
                <span className="text-slate-600">in </span>
                {m.inTokens.toLocaleString()}
              </span>
              <span className="text-slate-500">
                <span className="text-slate-600">out </span>
                {m.outTokens.toLocaleString()}
              </span>
              <span className="text-emerald-500/80">
                ${(m.cost * 100).toFixed(4)}¢
              </span>
            </div>
          )
        })}

        {/* Total row */}
        <div className="px-3 py-2 text-xs font-mono bg-slate-800/40 space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-slate-600 w-4">Σ</span>
            <span className="text-slate-300 font-semibold flex-1">Total</span>
            {llmStages.length > 0 && (
              <>
                <span className="text-white">
                  <span className="text-slate-500">in </span>{totalIn.toLocaleString()}
                </span>
                <span className="text-white">
                  <span className="text-slate-500">out </span>{totalOut.toLocaleString()}
                </span>
                <span className="text-emerald-400 font-semibold">
                  ${(totalCost * 100).toFixed(4)}¢
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-2 pl-6">
            <span className="text-slate-500">{completedStages.length} stages completed</span>
            <span className="ml-auto text-amber-400 font-semibold">{fmtMs(totalMs)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
