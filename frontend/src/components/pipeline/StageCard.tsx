import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import type { StageState } from '../../hooks/usePipelineStore'
import { usePipelineStore } from '../../hooks/usePipelineStore'
import type { CheckResult } from '../../types/events'

const STATUS_STYLES: Record<string, string> = {
  idle:      'border-[var(--color-border)] bg-[var(--color-surface)] text-slate-500',
  started:   'border-indigo-500/50 bg-indigo-500/5 text-indigo-300 animate-pulse',
  running:   'border-indigo-500/50 bg-indigo-500/10 text-indigo-200',
  completed: 'border-emerald-500/50 bg-emerald-500/5 text-emerald-300',
  error:     'border-red-500/50 bg-red-500/5 text-red-300',
}

const STATUS_ICON: Record<string, string> = {
  idle: '○', started: '◐', running: '◑', completed: '●', error: '✗',
}

function ChecksPopup({ stage, onClose }: { stage: StageState; onClose: () => void }) {
  const checks: CheckResult[] = stage.verification?.l1_checks ?? []
  const l1Rate = stage.verification?.l1_pass_rate ?? 0
  const l2Score = stage.verification?.l2_score

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl w-full max-w-sm shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white">
              {stage.id}. {stage.name}
            </span>
            <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${
              l1Rate === 1 ? 'bg-emerald-900/40 text-emerald-400' : 'bg-yellow-900/40 text-yellow-400'
            }`}>
              L1 {(l1Rate * 100).toFixed(0)}%
            </span>
            {l2Score != null && (
              <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${
                l2Score >= 0.85 ? 'bg-emerald-900/40 text-emerald-400' : 'bg-yellow-900/40 text-yellow-400'
              }`}>
                L2 {l2Score.toFixed(2)}
              </span>
            )}
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-white text-lg leading-none ml-2">×</button>
        </div>

        {/* Checks */}
        <div className="p-3 space-y-1.5 max-h-80 overflow-y-auto">
          {checks.length === 0 && (
            <p className="text-xs text-slate-500 italic text-center py-2">No checks recorded</p>
          )}
          {checks.map((c, i) => (
            <div
              key={i}
              className={`flex items-start gap-2 text-xs px-2.5 py-2 rounded-lg ${
                c.passed
                  ? 'bg-emerald-900/20 border border-emerald-800/30 text-emerald-300'
                  : c.severity === 'warn'
                  ? 'bg-yellow-900/20 border border-yellow-800/30 text-yellow-300'
                  : 'bg-red-900/20 border border-red-800/30 text-red-300'
              }`}
            >
              <span className="font-mono mt-0.5 text-sm leading-none flex-shrink-0">
                {c.passed ? '✓' : c.severity === 'warn' ? '△' : '✗'}
              </span>
              <div className="min-w-0">
                <p className="font-semibold">{c.name.replace(/_/g, ' ')}</p>
                {c.detail && <p className="opacity-70 mt-0.5 leading-relaxed">{c.detail}</p>}
              </div>
            </div>
          ))}
        </div>

        {/* Footer pass summary */}
        <div className="px-4 py-2 border-t border-[var(--color-border)] text-xs text-slate-500 text-right">
          {checks.filter(c => c.passed).length} / {checks.length} checks passed
        </div>
      </div>
    </div>
  )
}

interface Props {
  stage: StageState
  overrideSelected?: boolean
}

export function StageCard({ stage, overrideSelected }: Props) {
  const { selectedStage, setSelectedStage } = usePipelineStore()
  const isSelected = overrideSelected !== undefined ? overrideSelected : selectedStage === stage.id
  const [showChecks, setShowChecks] = useState(false)

  const l1Rate = stage.verification?.l1_pass_rate
  const l2Score = stage.verification?.l2_score

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2, delay: stage.id * 0.03 }}
        onClick={overrideSelected === undefined ? () => setSelectedStage(isSelected ? null : stage.id) : undefined}
        className={`border rounded-xl p-3 transition-all ${STATUS_STYLES[stage.status]} ${
          isSelected ? 'ring-2 ring-indigo-400/50' : ''
        } ${overrideSelected === undefined ? 'cursor-pointer' : ''}`}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-lg font-mono leading-none">{STATUS_ICON[stage.status]}</span>
            <div className="min-w-0">
              <p className="text-xs font-semibold truncate">
                <span className="text-slate-500 mr-1">{stage.id}.</span>
                {stage.name}
              </p>
              {stage.duration_ms != null && (
                <p className="text-xs opacity-60">{stage.duration_ms.toFixed(0)}ms</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            {l1Rate != null && (
              <button
                onClick={(e) => { e.stopPropagation(); setShowChecks(true) }}
                className={`text-xs px-1.5 py-0.5 rounded font-mono transition-opacity hover:opacity-75 ${
                  l1Rate === 1 ? 'bg-emerald-900/40 text-emerald-400' : 'bg-yellow-900/40 text-yellow-400'
                }`}
              >
                L1 {(l1Rate * 100).toFixed(0)}%
              </button>
            )}
            {l2Score != null && (
              <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${
                l2Score >= 0.85 ? 'bg-emerald-900/40 text-emerald-400' : 'bg-yellow-900/40 text-yellow-400'
              }`}>
                L2 {l2Score.toFixed(2)}
              </span>
            )}
          </div>
        </div>

        {/* Per-stage LLM token usage */}
        {stage.status === 'completed' && stage.payload?.llm_input_tokens != null && (
          <div className="mt-1.5 flex items-center gap-2 text-xs font-mono text-slate-500">
            <span className="text-slate-600">↳</span>
            <span><span className="text-slate-600">in </span>{(stage.payload.llm_input_tokens as number).toLocaleString()}</span>
            <span><span className="text-slate-600">out </span>{(stage.payload.llm_output_tokens as number ?? 0).toLocaleString()}</span>
            <span className="ml-auto text-emerald-500/80">${((stage.payload.llm_cost_usd as number ?? 0) * 100).toFixed(4)}¢</span>
          </div>
        )}
      </motion.div>

      {showChecks && <ChecksPopup stage={stage} onClose={() => setShowChecks(false)} />}
    </>
  )
}
