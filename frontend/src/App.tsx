import { useEffect, useMemo, useState } from 'react'
import { Header } from './components/layout/Header'
import type { AppPage } from './components/layout/Header'
import { DropZone } from './components/upload/DropZone'
import { DemoDocSelector } from './components/upload/DemoDocSelector'
import { StageCard } from './components/pipeline/StageCard'
import { StageDetail } from './components/pipeline/StageDetail'
import { AuditLog } from './components/pipeline/AuditLog'
import { LLMUsageSummary } from './components/pipeline/LLMUsageSummary'
import { FilePreviewModal } from './components/pipeline/FilePreviewModal'
import { AskBox } from './components/qa/AskBox'
import { StorageSummary } from './components/storage/StorageSummary'
import { JobTabs } from './components/pipeline/JobTabs'
import { CompareLayout } from './components/comparison/CompareLayout'
import { SystemDesignTab } from './components/pipeline/SystemDesignTab'
import { usePipelineStore } from './hooks/usePipelineStore'
import { usePipelineSockets } from './hooks/usePipelineSocket'

function SinglePipelineView() {
  const { stages, setSelectedStage, selectedStage, activeJobId, mode } = usePipelineStore()
  const [showPreview, setShowPreview] = useState(false)
  const [tab, setTab] = useState<'detail' | 'ask' | 'storage' | 'design'>('detail')
  const hasFile = stages.some((s) => s.id === 1 && s.status === 'completed')
  // For agent mode the cache_prefix is "" (same as custom). Map mode → pipeline.
  const pipelineForAsk: 'custom' | 'docling' = mode === 'docling' ? 'docling' : 'custom'

  return (
    <div className="flex-1 flex gap-4 min-h-0 overflow-hidden">
      {/* Left sidebar: scrollable stages list + sticky Pipeline Summary */}
      <div className="w-64 flex-shrink-0 flex flex-col min-h-0">
        {/* Stages — scrollable region (gets all the available vertical space) */}
        <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-1.5">
          {stages.map((s) => (
            <div key={s.id} onClick={() => setSelectedStage(selectedStage === s.id ? null : s.id)} className="cursor-pointer">
              <StageCard stage={s} />
            </div>
          ))}
        </div>
        {/* Pipeline Summary — pinned to bottom, always visible */}
        <div className="flex-shrink-0 mt-2 pt-2 border-t border-[var(--color-border)]">
          <LLMUsageSummary />
        </div>
      </div>

      {/* Inspector — Stage Detail / Ask anything tabs */}
      <div className="flex-1 flex flex-col border border-[var(--color-border)] rounded-xl bg-[var(--color-surface)] overflow-hidden">
        <div className="px-3 py-2 border-b border-[var(--color-border)] flex items-center gap-2">
          <div className="flex bg-[var(--color-bg)] rounded-lg p-0.5 border border-[var(--color-border)]">
            <button
              onClick={() => setTab('detail')}
              className={`text-xs px-2.5 py-1 rounded-md font-medium transition-colors ${
                tab === 'detail' ? 'bg-indigo-500/20 text-indigo-300' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              Stage Inspector
            </button>
            <button
              onClick={() => setTab('ask')}
              className={`text-xs px-2.5 py-1 rounded-md font-medium transition-colors ${
                tab === 'ask' ? 'bg-indigo-500/20 text-indigo-300' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              Ask anything 💬
            </button>
            <button
              onClick={() => setTab('storage')}
              className={`text-xs px-2.5 py-1 rounded-md font-medium transition-colors ${
                tab === 'storage' ? 'bg-indigo-500/20 text-indigo-300' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              Storage 📦
            </button>
            <button
              onClick={() => setTab('design')}
              className={`text-xs px-2.5 py-1 rounded-md font-medium transition-colors ${
                tab === 'design' ? 'bg-indigo-500/20 text-indigo-300' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              System Design 🧠
            </button>
          </div>
          <div className="flex-1" />
          {hasFile && activeJobId && (
            <button
              onClick={() => setShowPreview(true)}
              className="text-xs px-2 py-1 rounded-lg bg-indigo-500/15 text-indigo-400 hover:bg-indigo-500/25 hover:text-indigo-300 border border-indigo-500/30 transition-all font-medium"
            >
              Preview file ↗
            </button>
          )}
        </div>
        {tab === 'detail' && <StageDetail />}
        {tab === 'ask'     && <AskBox jobId={activeJobId} pipeline={pipelineForAsk} />}
        {tab === 'storage' && <StorageSummary jobId={activeJobId} />}
        {tab === 'design'  && <SystemDesignTab />}
      </div>

      {showPreview && activeJobId && (
        <FilePreviewModal jobId={activeJobId} onClose={() => setShowPreview(false)} />
      )}
    </div>
  )
}

function ComparePipelineView() {
  return <CompareLayout />
}

export default function App() {
  const [page, setPage] = useState<AppPage>('pipeline')
  const { mode, runs, jobOrder, addRun, removeRun, resetAll } = usePipelineStore()

  // Open one WebSocket per known job (rehydrated jobs included).
  // Backend replays buffered stage events on every WS connect, so the per-stage
  // UI rebuilds itself for any in-flight job after a page reload.
  usePipelineSockets(jobOrder)

  // On first mount, validate any persisted job IDs against the backend.
  // If the backend has restarted or garbage-collected the job, drop it from the
  // store so we don't keep trying to open a WS for a job that doesn't exist.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      for (const jobId of jobOrder) {
        try {
          const r = await fetch(`/api/jobs/${jobId}`)
          if (cancelled) return
          if (r.status === 404) removeRun(jobId)
        } catch {
          // network error / backend down — leave the run; user can retry.
        }
      }
    })()
    return () => { cancelled = true }
    // intentionally empty deps — runs once on mount with the rehydrated list
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleNewJob(id: string, filename: string) {
    addRun(id, filename, mode)
  }

  const modeBadge = {
    agent: { label: 'Mode D — Agent (auto)', color: 'text-fuchsia-400' },
  } as const

  const summary = useMemo(() => {
    const total = jobOrder.length
    if (total === 0) return null
    const done = jobOrder.filter((id) => runs[id]?.status === 'completed').length
    const running = jobOrder.filter((id) => {
      const s = runs[id]?.status
      return s === 'running' || s === 'queued'
    }).length
    return { total, done, running }
  }, [jobOrder, runs])

  return (
    <div className="h-screen flex flex-col bg-[var(--color-bg)]">
      <Header page={page} onPageChange={setPage} />

      {page === 'audit' ? (
        <div className="flex-1 p-6 min-h-0 overflow-hidden">
          <AuditLog />
        </div>
      ) : (
        <div className="flex-1 flex gap-4 p-4 min-h-0">
          {/* Sidebar */}
          <div className="w-64 flex-shrink-0 flex flex-col gap-4 overflow-y-auto">
            <div className="flex items-center justify-between gap-2">
              <div className={`text-xs font-medium ${modeBadge.agent.color}`}>
                {modeBadge.agent.label}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => resetAll()}
                  className="rounded-md border border-slate-700 px-2 py-1 text-[10px] font-medium text-slate-300 transition hover:border-slate-500 hover:text-white"
                >
                  Clear runs
                </button>
                {summary && (
                  <div className="text-[10px] text-slate-500 font-mono">
                    {summary.done}/{summary.total} done
                    {summary.running > 0 && <span className="text-indigo-400 ml-1">·{summary.running} live</span>}
                  </div>
                )}
              </div>
            </div>
            <DropZone onJobCreated={handleNewJob} maxFiles={5} />
            <DemoDocSelector onJobCreated={handleNewJob} />
          </div>

          {/* Main area: tabs above, then view */}
          <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
            <JobTabs />
            {mode === 'compare' ? <ComparePipelineView /> : <SinglePipelineView />}
          </div>
        </div>
      )}
    </div>
  )
}
