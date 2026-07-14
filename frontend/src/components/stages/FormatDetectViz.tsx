import type { StageState } from '../../hooks/usePipelineStore'

const FILE_TYPE: Record<string, { label: string; color: string; desc: string }> = {
  'application/pdf':                                                                  { label: 'PDF',  color: 'bg-red-900/40 text-red-300 border-red-700/40',         desc: 'Portable Document Format' },
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':               { label: 'XLSX', color: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40', desc: 'Excel Spreadsheet' },
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document':         { label: 'DOCX', color: 'bg-blue-900/40 text-blue-300 border-blue-700/40',       desc: 'Word Document' },
  'application/vnd.openxmlformats-officedocument.presentationml.presentation':       { label: 'PPTX', color: 'bg-orange-900/40 text-orange-300 border-orange-700/40', desc: 'PowerPoint Presentation' },
  'text/html':                                                                        { label: 'HTML', color: 'bg-yellow-900/40 text-yellow-300 border-yellow-700/40', desc: 'Web Page' },
}

const SUB_DESC: Record<string, { label: string; ok: boolean; note: string }> = {
  'text-native-pdf':   { label: 'Text-based PDF',      ok: true,  note: 'Text can be extracted directly — best quality.' },
  'scanned-pdf':       { label: 'Scanned PDF (image)',  ok: false, note: 'Pages are images of text — OCR needed, quality may vary.' },
  'spreadsheet-xlsx':  { label: 'Excel spreadsheet',   ok: true,  note: 'Rows and columns will be parsed sheet by sheet.' },
  'docx-document':     { label: 'Word document',        ok: true,  note: 'Paragraphs, headings, and tables will be extracted.' },
  'pptx-presentation': { label: 'PowerPoint slides',   ok: true,  note: 'Text from each slide will be extracted in order.' },
  'html-document':     { label: 'HTML web page',        ok: true,  note: 'HTML tags will be stripped, leaving clean text.' },
  'plain-text':        { label: 'Plain text file',      ok: true,  note: 'Read as-is with no conversion needed.' },
}

const LANG_FLAG: Record<string, string> = {
  en: '🇺🇸', fr: '🇫🇷', de: '🇩🇪', es: '🇪🇸', ja: '🇯🇵', zh: '🇨🇳',
}

const LANG_NAME: Record<string, string> = {
  en: 'English', fr: 'French', de: 'German', es: 'Spanish', ja: 'Japanese', zh: 'Chinese',
}

export function FormatDetectViz({ stage }: { stage: StageState }) {
  const p = stage.payload as {
    true_mime?: string
    encoding?: string
    sub_structure?: string
    is_scanned_pdf?: boolean
    language?: string
    confidence?: number
  }
  if (!p?.true_mime) return null

  const ft = FILE_TYPE[p.true_mime] ?? { label: p.true_mime, color: 'bg-slate-800 text-slate-300 border-slate-600', desc: 'Unknown format' }
  const sub = SUB_DESC[p.sub_structure ?? '']
  const flag = LANG_FLAG[p.language ?? ''] ?? '🌐'
  const langName = LANG_NAME[p.language ?? ''] ?? (p.language ?? 'Unknown')

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="px-3 py-2.5 rounded-lg bg-indigo-900/20 border border-indigo-700/30 text-xs text-slate-300 leading-relaxed">
        The pipeline inspected the file's internal structure — not just its name — to confirm what kind of document it really is and how to read it.
      </div>

      {/* File type */}
      <div>
        <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">File type</p>
        <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)]">
          <span className={`text-sm font-bold px-2.5 py-1 rounded-lg border ${ft.color}`}>{ft.label}</span>
          <span className="text-xs text-slate-400">{ft.desc}</span>
        </div>
      </div>

      {/* Structure */}
      {sub && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">How the content is stored</p>
          <div className={`flex items-start gap-2.5 px-3 py-2.5 rounded-lg border ${
            sub.ok ? 'bg-emerald-900/15 border-emerald-800/30' : 'bg-yellow-900/15 border-yellow-800/30'
          }`}>
            <span className="mt-0.5">{sub.ok ? '✓' : '⚠'}</span>
            <div>
              <p className={`text-xs font-medium ${sub.ok ? 'text-emerald-300' : 'text-yellow-300'}`}>{sub.label}</p>
              <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">{sub.note}</p>
            </div>
          </div>
        </div>
      )}

      {/* Details row */}
      <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] divide-y divide-[var(--color-border)]">
        {p.language && (
          <div className="flex items-center px-2.5 py-2 gap-2 text-xs">
            <span className="text-slate-500 flex-1">Language detected</span>
            <span className="text-slate-300">{flag} {langName}</span>
          </div>
        )}
        {p.encoding && (
          <div className="flex items-center px-2.5 py-2 gap-2 text-xs">
            <span className="text-slate-500 flex-1">Text encoding</span>
            <div className="text-right">
              <span className="text-slate-300 font-mono">{p.encoding}</span>
              {p.encoding === 'UTF-8' && <span className="text-slate-500 ml-2">(standard)</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
