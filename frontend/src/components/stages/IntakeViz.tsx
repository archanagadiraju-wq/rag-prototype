import type { StageState } from '../../hooks/usePipelineStore'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(2)} MB`
}

export function IntakeViz({ stage }: { stage: StageState }) {
  const p = stage.payload as {
    filename?: string
    size_bytes?: number
    source_type?: string
    sha256?: string
  }
  if (!p?.filename) return null

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="px-3 py-2.5 rounded-lg bg-indigo-900/20 border border-indigo-700/30 text-xs text-slate-300 leading-relaxed">
        Your document was received and logged. A unique fingerprint was calculated so we can detect if the file changes or gets corrupted.
      </div>

      {/* File card */}
      <div className="flex items-center gap-3 px-3 py-3 rounded-xl bg-[var(--color-bg)] border border-[var(--color-border)]">
        <span className="text-3xl">{p.source_type === 'upload' ? '⬆️' : '📂'}</span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-white truncate">{p.filename}</p>
          <p className="text-xs text-slate-400 mt-0.5">
            {p.source_type === 'upload' ? 'Uploaded by you' : 'Demo document'} · {formatBytes(p.size_bytes ?? 0)}
          </p>
        </div>
      </div>

      {/* Fingerprint */}
      {p.sha256 && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">File fingerprint (SHA-256)</p>
          <div className="px-2.5 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)]">
            <p className="text-[10px] font-mono text-slate-400 break-all leading-relaxed">{p.sha256}</p>
            <p className="text-[10px] text-slate-600 mt-1">This unique hash changes if even one byte of the file is different — used to detect corruption or tampering.</p>
          </div>
        </div>
      )}
    </div>
  )
}
