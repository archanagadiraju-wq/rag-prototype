import { useState } from 'react'
import { usePipelineStore } from '../../hooks/usePipelineStore'
import type { RunState } from '../../hooks/usePipelineStore'

function StatusDot({ status }: { status: RunState['status'] }) {
  if (status === 'running' || status === 'queued') {
    return <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse shrink-0" />
  }
  if (status === 'failed') {
    return <span className="w-2 h-2 rounded-full bg-red-400 shrink-0" />
  }
  if (status === 'cancelled') {
    return <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0" />
  }
  return <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
}

function Tab({ run, active, onClick, onClose }: {
  run: RunState
  active: boolean
  onClick: () => void
  onClose: () => void
}) {
  const [cancelling, setCancelling] = useState(false)
  const isInFlight = run.status === 'running' || run.status === 'queued'

  async function handleCancel(e: React.MouseEvent) {
    e.stopPropagation()
    if (cancelling) return
    if (!confirm(`Cancel ingestion of ${run.filename}? Work already done is kept on disk.`)) return
    setCancelling(true)
    try {
      await fetch(`/api/jobs/${run.jobId}`, { method: 'DELETE' })
    } catch {
      // Network failure: keep button enabled so user can retry.
      setCancelling(false)
    }
    // Don't clear `cancelling` on success — the WS will deliver the
    // cancelled-event and the status dot will flip to amber.
  }

  // Agent mode has DYNAMIC stages — the agent decides which tools to call,
  // so we can't show a fixed "N/T" denominator. Switch to a count-only label
  // ("N stages") and an indeterminate bar while running.
  //
  // For agent mode, run.status='completed' can flip true BETWEEN turns (all
  // emitted stages are completed but the agent's next turn hasn't started yet).
  // Use the dedicated final-stage event ("Agent finished") as the truth signal.
  const isAgent = run.pipeline === 'agent'
  const hasAgentFinishedEvent = isAgent && run.stages.some(
    (s) => s.name === 'Agent finished' && s.status === 'completed',
  )
  const isComplete = isAgent ? hasAgentFinishedEvent : (run.status === 'completed')
  const isFailed   = run.status === 'failed'

  let progressLabel: string
  if (isAgent) {
    progressLabel = isComplete
      ? `${run.progressDone} stages ✓`
      : isFailed
        ? `${run.progressDone} stages ✗`
        : `${run.progressDone} stages…`
  } else {
    progressLabel = `${run.progressDone}/${run.progressTotal}`
  }

  const fixedPct = run.progressTotal > 0
    ? Math.round((run.progressDone / run.progressTotal) * 100)
    : 0

  return (
    <div
      onClick={onClick}
      className={`relative group/tab flex items-center gap-2 px-3 py-2 border-r border-[var(--color-border)] cursor-pointer transition-all min-w-[170px] max-w-[260px] ${
        active
          ? 'bg-[var(--color-surface)] border-b-2 border-b-indigo-500'
          : 'bg-[var(--color-bg)] hover:bg-[var(--color-surface)]/60 border-b border-b-transparent'
      }`}
    >
      <StatusDot status={run.status} />
      <div className="flex-1 min-w-0">
        <p className={`text-xs font-medium truncate ${active ? 'text-white' : 'text-slate-300'}`}>
          {run.filename}
        </p>
        <div className="flex items-center gap-1.5 mt-0.5">
          <div className="flex-1 h-1 rounded-full bg-slate-800 overflow-hidden relative">
            {isAgent && !isComplete && !isFailed ? (
              // Indeterminate shimmer: the agent's total isn't known until it
              // finishes, so an exact percentage would be misleading.
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-indigo-400/70 to-transparent animate-shimmer" />
            ) : (
              <div
                className={`h-full rounded-full transition-all ${
                  isFailed ? 'bg-red-400'
                  : isComplete ? 'bg-emerald-400'
                  : 'bg-indigo-400'
                }`}
                style={{ width: isAgent && isComplete ? '100%' : `${fixedPct}%` }}
              />
            )}
          </div>
          <span className="text-[10px] text-slate-500 font-mono shrink-0">
            {progressLabel}
          </span>
        </div>
      </div>
      {isInFlight && (
        <button
          onClick={handleCancel}
          disabled={cancelling}
          title={cancelling ? 'Cancelling…' : 'Stop this ingestion'}
          className="opacity-0 group-hover/tab:opacity-100 text-amber-500 hover:text-amber-300 text-[11px] leading-none shrink-0 px-1 disabled:opacity-40 disabled:cursor-wait"
        >
          {cancelling ? '…' : '⏹'}
        </button>
      )}
      <button
        onClick={(e) => { e.stopPropagation(); onClose() }}
        title="Remove from tabs (does not cancel the job)"
        className="opacity-0 group-hover/tab:opacity-100 text-slate-600 hover:text-slate-300 text-sm leading-none shrink-0 px-0.5"
      >
        ×
      </button>
    </div>
  )
}

export function JobTabs() {
  const { runs, jobOrder, activeJobId, setActiveJobId, removeRun } = usePipelineStore()

  if (jobOrder.length === 0) return null

  return (
    <div className="flex items-stretch border-b border-[var(--color-border)] bg-[var(--color-bg)] overflow-x-auto">
      {jobOrder.map((id) => {
        const run = runs[id]
        if (!run) return null
        return (
          <Tab
            key={id}
            run={run}
            active={id === activeJobId}
            onClick={() => setActiveJobId(id)}
            onClose={() => removeRun(id)}
          />
        )
      })}
    </div>
  )
}
