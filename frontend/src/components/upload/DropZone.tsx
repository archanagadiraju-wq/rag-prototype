import { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { usePipelineStore } from '../../hooks/usePipelineStore'

interface Props {
  onJobCreated: (jobId: string, filename: string) => void
  /** Max files to accept in one drop. Default 5. */
  maxFiles?: number
}

const COMPARE_BULK_DISABLED = true   // compare mode = 2x cost per file; disabled for bulk by request

export function DropZone({ onJobCreated, maxFiles = 5 }: Props) {
  const { mode } = usePipelineStore()
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)

  const submitFiles = useCallback(
    async (files: File[]) => {
      const slice = files.slice(0, maxFiles)
      if (slice.length === 0) return

      if (slice.length > 1 && mode === 'compare' && COMPARE_BULK_DISABLED) {
        setError('Compare mode only supports one file at a time. Drop a single file or switch mode.')
        return
      }

      setUploading(true)
      setError(null)
      setProgress({ done: 0, total: slice.length })

      try {
        // Submit in parallel — backend already supports concurrent jobs.
        const tasks = slice.map(async (file) => {
          const form = new FormData()
          form.append('file', file)
          form.append('pipeline', mode)
          const res = await fetch('/api/jobs', { method: 'POST', body: form })
          if (!res.ok) throw new Error(`${file.name}: ${await res.text()}`)
          const { job_id } = await res.json()
          onJobCreated(job_id, file.name)
          setProgress((p) => p ? { ...p, done: p.done + 1 } : p)
        })
        await Promise.all(tasks)
      } catch (e) {
        setError(String(e))
      } finally {
        setUploading(false)
        setTimeout(() => setProgress(null), 800)
      }
    },
    [mode, onJobCreated, maxFiles]
  )

  const onDrop = useCallback((files: File[]) => {
    if (files.length) submitFiles(files)
  }, [submitFiles])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'text/html': ['.html', '.htm'],
      'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
    },
    maxFiles,
    disabled: uploading,
  })

  const compareWarn = mode === 'compare' && COMPARE_BULK_DISABLED

  return (
    <div className="space-y-3">
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
          isDragActive
            ? 'border-indigo-500 bg-indigo-500/10'
            : 'border-[var(--color-border)] hover:border-indigo-500/50'
        } ${uploading ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <input {...getInputProps()} />
        <div className="text-3xl mb-2">{uploading ? '⏳' : isDragActive ? '📂' : '📄'}</div>
        {uploading && progress ? (
          <>
            <p className="text-slate-300 text-sm font-medium">
              Starting {progress.total} pipeline{progress.total !== 1 ? 's' : ''}…
            </p>
            <p className="text-slate-500 text-xs mt-1">{progress.done}/{progress.total} created</p>
          </>
        ) : isDragActive ? (
          <p className="text-indigo-400 text-sm font-medium">Drop to ingest</p>
        ) : (
          <>
            <p className="text-slate-300 text-sm font-medium">
              {compareWarn ? 'Drop one document' : `Drop up to ${maxFiles} documents`}
            </p>
            <p className="text-slate-500 text-xs mt-1">
              PDF · DOCX · XLSX · HTML · PPTX
            </p>
            {compareWarn && (
              <p className="text-amber-500 text-[10px] mt-1.5">
                Compare mode — bulk upload disabled
              </p>
            )}
          </>
        )}
      </div>
      {error && <p className="text-red-400 text-xs bg-red-900/20 rounded-lg p-2">{error}</p>}
    </div>
  )
}
