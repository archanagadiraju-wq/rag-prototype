import type { StageState } from '../../hooks/usePipelineStore'

const PARSER_INFO: Record<string, { label: string; color: string }> = {
  pdfplumber:           { label: 'PDF Reader',        color: 'bg-red-900/40 text-red-300 border-red-700/40' },
  'python-docx':        { label: 'Word Reader',        color: 'bg-blue-900/40 text-blue-300 border-blue-700/40' },
  openpyxl:             { label: 'Spreadsheet Reader', color: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40' },
  'python-pptx':        { label: 'Slides Reader',      color: 'bg-orange-900/40 text-orange-300 border-orange-700/40' },
  beautifulsoup4:       { label: 'HTML Reader',         color: 'bg-yellow-900/40 text-yellow-300 border-yellow-700/40' },
  'plaintext-fallback': { label: 'Plain Text Reader',  color: 'bg-slate-800 text-slate-300 border-slate-600' },
  'docling-2.x':        { label: 'Docling AI Parser',  color: 'bg-violet-900/40 text-violet-300 border-violet-700/40' },
}

interface ParserPayload {
  parser_used?: string
  page_count?: number | null
  word_count?: number
  table_count?: number
  image_count?: number
  text_blocks?: { id: string; text: string; page?: number; heading_level?: number }[]
  tables?: { id: string; headers?: string[]; rows?: string[][]; as_markdown?: string }[]
  raw_text_preview?: string
}

export function computeExtractionConfidence(p: ParserPayload) {
  const parserReliability = p.parser_used === 'vision_ocr'
    ? 0.72
    : p.parser_used === 'plaintext-fallback'
      ? 0.6
      : p.parser_used === 'docling-2.x'
        ? 0.92
        : p.parser_used === 'pdfplumber'
          ? 0.9
          : p.parser_used === 'python-docx' || p.parser_used === 'openpyxl' || p.parser_used === 'python-pptx' || p.parser_used === 'beautifulsoup4'
            ? 0.95
            : 0.8

  const wordCount = Math.max(0, Number(p.word_count ?? 0))
  const textCoverage = wordCount >= 1500
    ? 1
    : wordCount >= 500
      ? 0.9
      : wordCount >= 200
        ? 0.75
        : wordCount >= 50
          ? 0.55
          : wordCount > 0
            ? 0.35
            : 0

  const blockCount = Math.max(0, Number(p.text_blocks?.length ?? 0))
  const tableCount = Math.max(0, Number(p.table_count ?? 0))
  const structuralEvidence = blockCount >= 10
    ? 1
    : blockCount >= 4
      ? 0.85
      : blockCount >= 1
        ? 0.7
        : tableCount > 0 || (p.image_count ?? 0) > 0
          ? 0.6
          : 0.4

  const score = Math.min(1, Math.max(0, 0.45 * parserReliability + 0.35 * textCoverage + 0.20 * structuralEvidence))
  const label = score >= 0.85 ? 'High' : score >= 0.65 ? 'Medium' : 'Low'
  const rationale = `The parser was ${Math.round(parserReliability * 100)}% reliable, the text body contained ${wordCount.toLocaleString()} words, and ${blockCount} structured sections/tables were recovered.`

  return { score, label, rationale }
}

export function ParserViz({ stage }: { stage: StageState }) {
  const p = stage.payload as ParserPayload
  if (!p?.parser_used) return null

  const info = PARSER_INFO[p.parser_used] ?? { label: p.parser_used, color: 'bg-slate-800 text-slate-300 border-slate-600' }
  const blocks = p.text_blocks ?? []
  const tables = p.tables ?? []
  const headings = blocks.filter((b) => (b.heading_level ?? 0) > 0)

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="px-3 py-2.5 rounded-lg bg-indigo-900/20 border border-indigo-700/30 text-xs text-slate-300 leading-relaxed">
        The document was read from start to finish. All text, headings, tables, and images were extracted and stored separately so each can be handled appropriately.
      </div>

      {/* Tool used */}
      <div className="flex items-center gap-2">
        <span className={`text-xs font-bold px-2.5 py-1 rounded-lg border ${info.color}`}>{info.label}</span>
        <span className="text-xs text-slate-500">was used to read this file</span>
      </div>

      {/* What was found */}
      <div>
        <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">What was found</p>
        <div className="grid grid-cols-2 gap-1.5">
          {p.page_count != null && (
            <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
              <p className="text-lg font-bold text-white">{p.page_count}</p>
              <p className="text-xs text-slate-400">pages</p>
            </div>
          )}
          <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
            <p className="text-lg font-bold text-white">{(p.word_count ?? 0).toLocaleString()}</p>
            <p className="text-xs text-slate-400">words extracted</p>
          </div>
          <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
            <p className="text-lg font-bold text-white">{p.table_count ?? 0}</p>
            <p className="text-xs text-slate-400">tables found</p>
          </div>
          <div className="rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] px-2.5 py-2">
            <p className="text-lg font-bold text-white">{blocks.length}</p>
            <p className="text-xs text-slate-400">text sections</p>
          </div>
        </div>
      </div>

      {/* Text preview */}
      {p.raw_text_preview && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">Sample of extracted text</p>
          <div className="text-xs text-slate-300 bg-[var(--color-bg)] rounded-lg p-2.5 border border-[var(--color-border)] max-h-24 overflow-y-auto leading-relaxed whitespace-pre-wrap">
            {p.raw_text_preview}
          </div>
        </div>
      )}

      {/* Document outline */}
      {headings.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">Document structure</p>
          <div className="space-y-0.5 max-h-28 overflow-y-auto rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] p-2">
            {headings.slice(0, 12).map((b) => (
              <div key={b.id} className="text-xs text-slate-300 truncate flex items-center gap-1.5"
                style={{ paddingLeft: `${((b.heading_level ?? 1) - 1) * 12}px` }}>
                <span className="text-slate-600 text-[10px] shrink-0">
                  {b.heading_level === 1 ? '■' : b.heading_level === 2 ? '▸' : '·'}
                </span>
                {b.text}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tables preview */}
      {tables.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
            Tables found ({tables.length})
          </p>
          <div className="space-y-2 max-h-40 overflow-y-auto">
            {tables.slice(0, 3).map((tbl) => (
              <div key={tbl.id} className="rounded-lg border border-[var(--color-border)] overflow-hidden">
                {tbl.headers && tbl.headers.length > 0 && (
                  <div className="flex gap-2 px-2 py-1.5 bg-slate-800/50 border-b border-[var(--color-border)]">
                    {tbl.headers.slice(0, 5).map((h, i) => (
                      <span key={i} className="text-xs text-slate-400 font-medium truncate flex-1">{h}</span>
                    ))}
                  </div>
                )}
                {(tbl.rows ?? []).slice(0, 2).map((row, ri) => (
                  <div key={ri} className="flex gap-2 px-2 py-1 border-b border-[var(--color-border)] last:border-0">
                    {row.slice(0, 5).map((cell, ci) => (
                      <span key={ci} className="text-xs text-slate-300 truncate flex-1">{cell}</span>
                    ))}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
