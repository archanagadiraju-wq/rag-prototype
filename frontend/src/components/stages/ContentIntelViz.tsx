import type { StageState } from '../../hooks/usePipelineStore'

const DOC_TYPE_LABEL: Record<string, string> = {
  research_paper:   'Research Paper',
  financial_report: 'Financial Report',
  contract:         'Legal Contract',
  technical_spec:   'Technical Specification',
  presentation:     'Presentation / Slide Deck',
  memo:             'Memo',
  other:            'Other',
}

const DOC_TYPE_COLOR: Record<string, string> = {
  research_paper:   'bg-purple-900/40 text-purple-300 border-purple-700/40',
  financial_report: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
  contract:         'bg-blue-900/40 text-blue-300 border-blue-700/40',
  technical_spec:   'bg-cyan-900/40 text-cyan-300 border-cyan-700/40',
  presentation:     'bg-orange-900/40 text-orange-300 border-orange-700/40',
  memo:             'bg-yellow-900/40 text-yellow-300 border-yellow-700/40',
}

const ENTITY_LABELS: Record<string, { label: string; color: string }> = {
  PERSON:  { label: 'People',        color: 'bg-violet-900/40 text-violet-300' },
  ORG:     { label: 'Organizations', color: 'bg-sky-900/40 text-sky-300' },
  PRODUCT: { label: 'Products',      color: 'bg-amber-900/40 text-amber-300' },
  GPE:     { label: 'Locations',     color: 'bg-teal-900/40 text-teal-300' },
  DATE:    { label: 'Dates',         color: 'bg-indigo-900/40 text-indigo-300' },
  MONEY:   { label: 'Money',         color: 'bg-emerald-900/40 text-emerald-300' },
  LAW:     { label: 'Laws / Regs',   color: 'bg-rose-900/40 text-rose-300' },
}

interface Entity { text: string; label: string }

interface ContentIntelPayload {
  doc_type?: string
  doc_type_confidence?: number
  domain?: string
  language?: string
  summary?: string
  content_flags?: string[]
  entities?: Entity[]
  key_dates?: string[]
  llm_input_tokens?: number
  llm_output_tokens?: number
  llm_cost_usd?: number
}

const FLAG_LABELS: Record<string, string> = {
  contains_tables:  'Has tables',
  contains_images:  'Has images',
  multi_column:     'Multi-column layout',
  scanned_content:  'Scanned / image-based',
  bounding_box_provenance: 'Layout coordinates tracked',
}

export function ContentIntelViz({ stage }: { stage: StageState }) {
  const p = stage.payload as ContentIntelPayload
  if (!p?.doc_type) return null

  const docTypeLabel = DOC_TYPE_LABEL[p.doc_type ?? 'other'] ?? p.doc_type ?? 'Other'
  const docTypeColor = DOC_TYPE_COLOR[p.doc_type ?? 'other'] ?? 'bg-slate-800 text-slate-300 border-slate-600'
  const entities = p.entities ?? []
  const flags = p.content_flags ?? []
  const keyDates = p.key_dates ?? []

  const entityGroups = entities.reduce<Record<string, Entity[]>>((acc, e) => {
    if (!acc[e.label]) acc[e.label] = []
    acc[e.label].push(e)
    return acc
  }, {})

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="px-3 py-2.5 rounded-lg bg-indigo-900/20 border border-indigo-700/30 text-xs text-slate-300 leading-relaxed">
        Claude AI read a sample of the document and identified what kind of document it is, what field it belongs to, and pulled out key people, dates, and organizations mentioned.
      </div>

      {/* Classification */}
      <div>
        <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">What kind of document is this?</p>
        <div className="px-3 py-2.5 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs font-bold px-2.5 py-1 rounded-lg border ${docTypeColor}`}>{docTypeLabel}</span>
            <span className="text-xs text-slate-400">in the <span className="text-slate-300">{p.domain ?? 'general'}</span> domain</span>
          </div>
        </div>
      </div>

      {/* AI cost */}
      {p.llm_input_tokens != null && (
        <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700/50 text-xs">
          <span className="text-slate-500">Claude claude-haiku-4-5</span>
          <span className="text-slate-500 ml-1">read</span>
          <span className="text-slate-300">{(p.llm_input_tokens ?? 0).toLocaleString()} tokens</span>
          <span className="text-slate-500">wrote</span>
          <span className="text-slate-300">{(p.llm_output_tokens ?? 0).toLocaleString()}</span>
          <span className="ml-auto text-emerald-400 font-mono">${((p.llm_cost_usd ?? 0) * 100).toFixed(4)}¢</span>
        </div>
      )}

      {/* Summary */}
      {p.summary && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">AI-generated summary</p>
          <div className="text-xs text-slate-300 bg-[var(--color-bg)] rounded-lg p-2.5 border border-[var(--color-border)] leading-relaxed italic">
            "{p.summary}"
          </div>
        </div>
      )}

      {/* Content flags */}
      {flags.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">Content features detected</p>
          <div className="flex flex-wrap gap-1.5">
            {flags.map((f) => (
              <span key={f} className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                {FLAG_LABELS[f] ?? f.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Named entities */}
      {entities.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
            Key mentions found ({entities.length} total)
          </p>
          <div className="space-y-2 max-h-40 overflow-y-auto">
            {Object.entries(entityGroups).map(([label, items]) => {
              const info = ENTITY_LABELS[label] ?? { label, color: 'bg-slate-800 text-slate-300' }
              return (
                <div key={label} className="flex items-start gap-2">
                  <span className="text-[10px] text-slate-500 w-20 shrink-0 pt-0.5 uppercase tracking-wider">{info.label}</span>
                  <div className="flex flex-wrap gap-1">
                    {items.map((e, i) => (
                      <span key={i} className={`text-xs px-1.5 py-0.5 rounded ${info.color}`}>{e.text}</span>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Key dates */}
      {keyDates.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">Key dates mentioned</p>
          <div className="flex flex-wrap gap-1.5">
            {keyDates.map((d, i) => (
              <span key={i} className="text-xs px-2 py-0.5 rounded bg-indigo-900/30 text-indigo-300 border border-indigo-800/40 font-mono">
                {d}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
