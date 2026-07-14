import type { StageState } from '../../hooks/usePipelineStore'

interface MetadataPayload {
  sample_metadata?: Record<string, unknown>
  total_metadata_keys?: number
  filterable_fields?: string[]
}

const FIELD_LABELS: Record<string, { label: string; desc: string }> = {
  doc_type:        { label: 'Document type',   desc: 'Filter results to only this kind of document' },
  domain:          { label: 'Domain / field',  desc: 'e.g. only medical, only financial' },
  page:            { label: 'Page number',     desc: 'Find chunks from a specific page' },
  pipeline:        { label: 'Pipeline',        desc: 'Custom vs Docling results' },
  source_filename: { label: 'Filename',        desc: 'Filter by which document it came from' },
  chunk_idx:       { label: 'Chunk position',  desc: 'Get chunks near the start or end of a doc' },
  heading_path:    { label: 'Section heading', desc: 'Find chunks under a specific section' },
}

const META_LABELS: Record<string, string> = {
  doc_id:          'Document ID',
  chunk_id:        'Chunk ID',
  chunk_idx:       'Position in document',
  page:            'Source page',
  heading_path:    'Section heading',
  pipeline:        'Pipeline used',
  doc_type:        'Document type',
  domain:          'Domain / field',
  source_filename: 'Source filename',
}

export function MetadataViz({ stage }: { stage: StageState }) {
  const p = stage.payload as MetadataPayload
  if (!p) return null

  const sample = p.sample_metadata ?? {}
  const fields = p.filterable_fields ?? []

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="px-3 py-2.5 rounded-lg bg-indigo-900/20 border border-indigo-700/30 text-xs text-slate-300 leading-relaxed">
        Every chunk was tagged with information about where it came from. These tags let you filter future searches — for example, "only search in financial documents" or "only page 5 onwards."
      </div>

      {/* Filterable fields */}
      {fields.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
            Fields you can filter searches by
          </p>
          <div className="space-y-1.5">
            {fields.map((f) => {
              const info = FIELD_LABELS[f]
              return (
                <div key={f} className="flex items-start gap-2.5 px-2.5 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)]">
                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-1.5 flex-shrink-0" />
                  <div>
                    <p className="text-xs font-medium text-slate-300">{info?.label ?? f.replace(/_/g, ' ')}</p>
                    {info?.desc && <p className="text-[10px] text-slate-500 mt-0.5">{info.desc}</p>}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Sample metadata from first chunk */}
      {Object.keys(sample).length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
            Example — tags on chunk #1
          </p>
          <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] divide-y divide-[var(--color-border)]">
            {Object.entries(sample).map(([k, v]) => (
              <div key={k} className="flex items-start gap-2 px-2.5 py-1.5">
                <span className="text-[10px] text-slate-500 w-28 shrink-0 pt-0.5">
                  {META_LABELS[k] ?? k.replace(/_/g, ' ')}
                </span>
                <span className="text-xs text-slate-300 font-mono break-all">
                  {v == null
                    ? <span className="text-slate-600">—</span>
                    : String(v).length > 55 ? String(v).slice(0, 55) + '…' : String(v)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
