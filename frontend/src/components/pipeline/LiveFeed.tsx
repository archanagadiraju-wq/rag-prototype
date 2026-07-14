import { useState } from 'react'
import { usePipelineStore } from '../../hooks/usePipelineStore'

export function LiveFeed() {
  const wsLog = usePipelineStore((s) => s.wsLog)
  const [open, setOpen] = useState(false)

  return (
    <div className="border border-[var(--color-border)] rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 bg-[var(--color-surface)] text-xs text-slate-400 hover:text-white"
      >
        <span>Raw WebSocket Feed ({wsLog.length} events)</span>
        <span>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="max-h-48 overflow-y-auto bg-[var(--color-bg)] p-2 space-y-1">
          {wsLog.length === 0 ? (
            <p className="text-xs text-slate-600 text-center py-4">No events yet</p>
          ) : (
            [...wsLog].reverse().map((e, i) => (
              <div key={i} className="text-xs font-mono text-slate-400 flex gap-2">
                <span
                  className={`flex-shrink-0 ${
                    e.status === 'completed'
                      ? 'text-emerald-400'
                      : e.status === 'error'
                      ? 'text-red-400'
                      : 'text-indigo-400'
                  }`}
                >
                  [{e.status.toUpperCase()}]
                </span>
                <span>
                  S{e.stage_id} {e.stage_name}
                </span>
                {e.duration_ms != null && (
                  <span className="text-slate-600">{e.duration_ms.toFixed(0)}ms</span>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
