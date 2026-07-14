import { useEffect, useState } from 'react'
import { usePipelineStore } from '../../hooks/usePipelineStore'

interface Props {
  jobId: string
  onClose: () => void
}

export function FilePreviewModal({ jobId, onClose }: Props) {
  const stages  = usePipelineStore((s) => s.stages)
  const [iframeError, setIframeError] = useState(false)

  const stage1   = stages.find((s) => s.id === 1 && s.status === 'completed')
  const filename = (stage1?.payload?.filename as string) ?? 'document'
  const ext      = filename.split('.').pop()?.toUpperCase() ?? 'FILE'

  const renderedUrl = `/api/jobs/${jobId}/rendered`
  const rawUrl      = `/api/jobs/${jobId}/file`

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl flex flex-col shadow-2xl"
        style={{ width: '88vw', height: '88vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--color-border)] shrink-0">
          <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300 font-mono font-bold shrink-0">
            {ext}
          </span>
          <span className="text-sm text-slate-300 font-medium truncate flex-1">{filename}</span>
          <a
            href={rawUrl}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-slate-500 hover:text-indigo-300 transition-colors shrink-0"
          >
            download ↓
          </a>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-white transition-colors text-xl leading-none ml-1 shrink-0"
          >
            ×
          </button>
        </div>

        {/* Body — always attempt iframe, backend handles conversion */}
        <div className="flex-1 overflow-hidden rounded-b-xl relative">
          {iframeError ? (
            <div className="flex items-center justify-center h-full text-slate-500 text-sm">
              Preview unavailable — <a href={rawUrl} className="text-indigo-400 ml-1 underline" target="_blank" rel="noreferrer">download file</a>
            </div>
          ) : (
            <iframe
              src={renderedUrl}
              className="w-full h-full border-0 bg-white"
              title={filename}
              sandbox="allow-same-origin allow-scripts"
              onError={() => setIframeError(true)}
            />
          )}
        </div>
      </div>
    </div>
  )
}
