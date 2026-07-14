import { useEffect, useState } from 'react'
import { usePipelineStore } from '../../hooks/usePipelineStore'
import type { DemoDoc } from '../../types/events'

const DOMAIN_ICONS: Record<string, string> = {
  medical: '🧬', financial: '📊', legal: '⚖️', technical: '⚙️',
}

// Shown immediately — replaced by live API response if backend is up
const FALLBACK_DOCS: DemoDoc[] = [
  { id: '01', filename: '01_pharmaceutical_trial.pdf',  doc_type: 'research_paper',  domain: 'medical',    description: 'Multi-column clinical trial PDF with merged-cell tables', has_ground_truth: true },
  { id: '02', filename: '02_financial_model.xlsx',      doc_type: 'financial_report', domain: 'financial',  description: '6-sheet SaaS financial model with cross-sheet formulas',  has_ground_truth: true },
  { id: '03', filename: '03_vendor_contract.docx',      doc_type: 'contract',         domain: 'legal',      description: 'Enterprise vendor contract with H1→H3 hierarchy + SLA',  has_ground_truth: true },
  { id: '04', filename: '04_technical_spec.html',       doc_type: 'technical_spec',   domain: 'technical',  description: 'API docs with code blocks, endpoint tables, error codes',  has_ground_truth: true },
  { id: '05', filename: '05_board_presentation.pptx',   doc_type: 'presentation',     domain: 'financial',  description: '22-slide Series B board deck with image-only tables',      has_ground_truth: true },
  { id: '06', filename: '06_vision_ocr_demo.pdf',       doc_type: 'financial_report', domain: 'financial',  description: '4-page PDF: typed text + table + chart image + scanned memo page', has_ground_truth: false },
]

interface Props {
  onJobCreated: (jobId: string, filename: string) => void
}

export function DemoDocSelector({ onJobCreated }: Props) {
  const { mode } = usePipelineStore()
  const [docs, setDocs] = useState<DemoDoc[]>(FALLBACK_DOCS)
  const [backendUp, setBackendUp] = useState<boolean | null>(null)
  const [loading, setLoading] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/demo-docs')
      .then((r) => r.json())
      .then((data) => { setDocs(data); setBackendUp(true) })
      .catch(() => setBackendUp(false))
  }, [])

  const selectDoc = async (doc: DemoDoc) => {
    if (!backendUp) return
    setLoading(doc.id)

    const form = new FormData()
    form.append('demo_doc', doc.filename)
    form.append('pipeline', mode)

    try {
      const res = await fetch('/api/jobs', { method: 'POST', body: form })
      const { job_id } = await res.json()
      onJobCreated(job_id, doc.filename)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(null)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs text-slate-500 font-medium uppercase tracking-wider">Demo Documents</p>
        <span
          className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
            backendUp === null
              ? 'bg-slate-800 text-slate-500'
              : backendUp
              ? 'bg-emerald-900/40 text-emerald-400'
              : 'bg-red-900/40 text-red-400'
          }`}
        >
          {backendUp === null ? 'connecting…' : backendUp ? 'backend ●' : 'backend offline'}
        </span>
      </div>

      <div className="space-y-1.5">
        {docs.map((doc) => (
          <div key={doc.id} className="relative group/row">
            <button
              onClick={() => selectDoc(doc)}
              disabled={!!loading || !backendUp}
              title={!backendUp ? 'Start the backend first: uvicorn main:app --port 8000' : undefined}
              className={`w-full text-left px-3 py-2 rounded-lg border transition-all group ${
                backendUp
                  ? 'bg-[var(--color-bg)] hover:bg-indigo-500/10 border-[var(--color-border)] hover:border-indigo-500/50 cursor-pointer'
                  : 'bg-[var(--color-bg)] border-[var(--color-border)] opacity-50 cursor-not-allowed'
              }`}
            >
              <div className="flex items-center gap-2 pr-7">
                <span className="text-base">{DOMAIN_ICONS[doc.domain] ?? '📄'}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-slate-300 group-hover:text-white truncate">{doc.filename}</p>
                  <p className="text-xs text-slate-500 truncate">{doc.description}</p>
                </div>
                {loading === doc.id && <span className="text-xs text-indigo-400 animate-pulse">…</span>}
              </div>
            </button>
            <a
              href={`/api/demo-docs/${doc.filename}`}
              download={doc.filename}
              onClick={(e) => e.stopPropagation()}
              title={`Download ${doc.filename}`}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded text-slate-600 hover:text-slate-300 hover:bg-slate-700/50 opacity-0 group-hover/row:opacity-100 transition-all"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
            </a>
          </div>
        ))}
      </div>

      {backendUp === false && (
        <p className="text-xs text-red-400 mt-2 bg-red-900/20 rounded-lg p-2">
          Backend offline. Run:<br />
          <code className="font-mono">cd backend && .venv/bin/uvicorn main:app --port 8000</code>
        </p>
      )}
    </div>
  )
}
