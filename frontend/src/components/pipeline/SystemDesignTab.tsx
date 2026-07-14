import { useState } from 'react'

type SubTab = 'tools' | 'workflow'

type ToolDefinition = {
  name: string
  when: string
  description: string
  requiredTools: string[]
  prompt: string
  config: string
}

const systemPrompt = `You are a document-ingestion agent for a RAG (Retrieval Augmented Generation) retrieval system. Your single responsibility: take one document, decide what's inside, and store it for later semantic + SQL retrieval. You drive a tool catalog adaptively — there is no fixed pipeline.

Hard constraints:
1. inspect_document MUST be your FIRST call.
2. A parse_* tool MUST run before chunk_text.
3. chunk_text MUST run before embed_and_index.
4. finalize MUST be the LAST call.`

const tools: ToolDefinition[] = [
  {
    name: 'inspect_document',
    when: 'Always first',
    description: 'ALWAYS CALL FIRST. Returns the document\'s format, size, page count, whether text is natively extractable, whether it contains images, whether it appears scanned (low extractable text per page), and a short text sample. Use this signal to pick the right parser.',
    requiredTools: [],
    prompt: 'ALWAYS CALL FIRST. Returns the document\'s format, size, page count, whether text is natively extractable, whether it contains images, whether it appears scanned (low extractable text per page), and a short text sample. Use this signal to pick the right parser.',
    config: '{"name":"inspect_document","description":"ALWAYS CALL FIRST. Returns the document\'s format, size, page count, whether text is natively extractable, whether it contains images, whether it appears scanned (low extractable text per page), and a short text sample. Use this signal to pick the right parser."}',
  },
  {
    name: 'parse_pdf_native',
    when: 'Born-digital PDF',
    description: 'Fast text+table extraction for born-digital PDFs using pdfplumber. Use when inspect_document reports has_extractable_text=true and is_scanned=false. Does NOT do OCR — will miss content on scanned pages.',
    requiredTools: ['inspect_document'],
    prompt: 'Fast text+table extraction for born-digital PDFs using pdfplumber. Use when inspect_document reports has_extractable_text=true and is_scanned=false. Does NOT do OCR — will miss content on scanned pages.',
    config: '{"name":"parse_pdf_native","description":"Fast text+table extraction for born-digital PDFs using pdfplumber. Use when inspect_document reports has_extractable_text=true and is_scanned=false. Does NOT do OCR — will miss content on scanned pages."}',
  },
  {
    name: 'parse_with_docling',
    when: 'Scanned or complex PDF',
    description: 'Heavy ML-based parsing using IBM Docling: TableFormer for tables, RapidOCR for scanned pages, layout-aware text extraction. SLOW: ~7s per page on CPU. Use only when the doc is scanned OR has complex tables that pdfplumber will mangle. Returns chunks, tables, and OCR\'d content.',
    requiredTools: ['inspect_document'],
    prompt: 'Heavy ML-based parsing using IBM Docling: TableFormer for tables, RapidOCR for scanned pages, layout-aware text extraction. SLOW: ~7s per page on CPU. Use only when the doc is scanned OR has complex tables that pdfplumber will mangle. Returns chunks, tables, and OCR\'d content.',
    config: '{"name":"parse_with_docling","description":"Heavy ML-based parsing using IBM Docling: TableFormer for tables, RapidOCR for scanned pages, layout-aware text extraction. SLOW: ~7s per page on CPU. Use only when the doc is scanned OR has complex tables that pdfplumber will mangle. Returns chunks, tables, and OCR\'d content."}',
  },
  {
    name: 'parse_with_vision_ocr',
    when: 'Fully scanned or broken-font PDF',
    description: 'Last-resort OCR via Claude vision: renders every PDF page to a PNG and asks Claude to transcribe text + extract tables. Use when inspect_document reports the document is fully scanned, has CID-encoded/broken fonts (sample_text full of \'(cid:N)\' codes), or when parse_with_docling has already timed out.',
    requiredTools: ['inspect_document'],
    prompt: 'Last-resort OCR via Claude vision: renders every PDF page to a PNG and asks Claude to transcribe text + extract tables. Use when inspect_document reports the document is fully scanned, has CID-encoded/broken fonts (sample_text full of \'(cid:N)\' codes), or when parse_with_docling has already timed out.',
    config: '{"name":"parse_with_vision_ocr","description":"Last-resort OCR via Claude vision: renders every PDF page to a PNG and asks Claude to transcribe text + extract tables. Use when inspect_document reports the document is fully scanned, has CID-encoded/broken fonts (sample_text full of \'(cid:N)\' codes), or when parse_with_docling has already timed out."}',
  },
  {
    name: 'parse_office_document',
    when: 'DOCX, PPTX, XLSX, HTML',
    description: 'Parse a DOCX, PPTX, XLSX, or HTML file using format-specific libraries (python-docx, openpyxl, etc.). Use for non-PDF office formats.',
    requiredTools: ['inspect_document'],
    prompt: 'Parse a DOCX, PPTX, XLSX, or HTML file using format-specific libraries (python-docx, openpyxl, etc.). Use for non-PDF office formats.',
    config: '{"name":"parse_office_document","description":"Parse a DOCX, PPTX, XLSX, or HTML file using format-specific libraries (python-docx, openpyxl, etc.). Use for non-PDF office formats."}',
  },
  {
    name: 'chunk_text',
    when: 'After any parser',
    description: 'Smart heading-aware chunking (~300 tokens, 50-token overlap). Call AFTER a parser has populated text_blocks. Required before embed_and_index.',
    requiredTools: ['inspect_document', 'parse_*'],
    prompt: 'Smart heading-aware chunking (~300 tokens, 50-token overlap). Call AFTER a parser has populated text_blocks. Required before embed_and_index.',
    config: '{"name":"chunk_text","description":"Smart heading-aware chunking (~300 tokens, 50-token overlap). Call AFTER a parser has populated text_blocks. Required before embed_and_index."}',
  },
  {
    name: 'describe_tables',
    when: 'When tables are found',
    description: 'MANDATORY when inspect_document reported has_tables=true. Generates one-sentence Claude descriptions for every structured table the parser extracted, then builds a table_summary chunk per table and pushes them to the embedding queue.',
    requiredTools: ['inspect_document', 'parse_*', 'chunk_text'],
    prompt: 'MANDATORY when inspect_document reported has_tables=true. Generates one-sentence Claude descriptions for every structured table the parser extracted, then builds a table_summary chunk per table and pushes them to the embedding queue.',
    config: '{"name":"describe_tables","description":"MANDATORY when inspect_document reported has_tables=true. Generates one-sentence Claude descriptions for every structured table the parser extracted, then builds a table_summary chunk per table and pushes them to the embedding queue."}',
  },
  {
    name: 'caption_images',
    when: 'When visuals matter',
    description: 'Process visual content ONLY. Two things: one-sentence Claude vision caption per embedded image, and structured OCR on any image-only/scanned pages. Skip if has_images=false. Skip if images are purely decorative.',
    requiredTools: ['inspect_document', 'parse_*'],
    prompt: 'Process visual content ONLY. Two things: one-sentence Claude vision caption per embedded image, and structured OCR on any image-only/scanned pages. Skip if has_images=false. Skip if images are purely decorative.',
    config: '{"name":"caption_images","description":"Process visual content ONLY. Two things: one-sentence Claude vision caption per embedded image, and structured OCR on any image-only/scanned pages. Skip if has_images=false. Skip if images are purely decorative."}',
  },
  {
    name: 'embed_and_index',
    when: 'After chunking',
    description: 'Embed chunks with text-embedding-3-large and upsert into Qdrant. This is the terminal step for vector retrieval — required for the doc to be queryable. Call after chunk_text.',
    requiredTools: ['inspect_document', 'parse_*', 'chunk_text'],
    prompt: 'Embed chunks with text-embedding-3-large and upsert into Qdrant. This is the terminal step for vector retrieval — required for the doc to be queryable. Call after chunk_text.',
    config: '{"name":"embed_and_index","description":"Embed chunks with text-embedding-3-large and upsert into Qdrant. This is the terminal step for vector retrieval — required for the doc to be queryable. Call after chunk_text."}',
  },
  {
    name: 'store_tables_sql',
    when: 'Structured tables exist',
    description: 'Index extracted structured tables into a per-job SQLite database so SQL-routed questions can be answered exactly. Call only if a parser found structured tables with headers and rows.',
    requiredTools: ['inspect_document', 'parse_*'],
    prompt: 'Index extracted structured tables into a per-job SQLite database so SQL-routed questions can be answered exactly. Call only if a parser found structured tables with headers and rows.',
    config: '{"name":"store_tables_sql","description":"Index extracted structured tables into a per-job SQLite database so SQL-routed questions can be answered exactly. Call only if a parser found structured tables with headers and rows."}',
  },
  {
    name: 'extract_entities',
    when: 'Natural-language prose is rich',
    description: 'Build a knowledge graph: named entities (PERSON, ORG, GPE, DATE, MONEY) and their co-occurrences across chunks. Useful for entity-anchored questions. Skip for table-only documents or purely procedural text.',
    requiredTools: ['inspect_document', 'chunk_text'],
    prompt: 'Build a knowledge graph: named entities (PERSON, ORG, GPE, DATE, MONEY) and their co-occurrences across chunks. Useful for entity-anchored questions. Skip for table-only documents or purely procedural text.',
    config: '{"name":"extract_entities","description":"Build a knowledge graph: named entities (PERSON, ORG, GPE, DATE, MONEY) and their co-occurrences across chunks. Useful for entity-anchored questions. Skip for table-only documents or purely procedural text."}',
  },
  {
    name: 'finalize',
    when: 'Last step',
    description: 'Call when ingestion is complete. Provide a short summary of what you did and any caveats. This stops the agent loop.',
    requiredTools: ['inspect_document', 'parse_*', 'chunk_text', 'embed_and_index'],
    prompt: 'Call when ingestion is complete. Provide a short summary of what you did and any caveats. This stops the agent loop.',
    config: '{"name":"finalize","description":"Call when ingestion is complete. Provide a short summary of what you did and any caveats. This stops the agent loop."}',
  },
]

function copyText(text: string) {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text)
  }
  return Promise.resolve()
}

export function SystemDesignTab() {
  const [subTab, setSubTab] = useState<SubTab>('tools')
  const [selectedTool, setSelectedTool] = useState<ToolDefinition | null>(null)
  const [copiedLabel, setCopiedLabel] = useState<string | null>(null)

  const handleCopy = async (label: string, text: string) => {
    await copyText(text)
    setCopiedLabel(label)
    window.setTimeout(() => setCopiedLabel(null), 1400)
  }

  return (
    <div className="h-full overflow-y-auto p-4 text-slate-200">
      <div className="mb-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)]/80 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-white">Agent design reference</h3>
            <p className="mt-1 text-xs text-slate-400">
              Use these tabs to copy-paste tool prompts into another agent system or study the full document-processing pathway.
            </p>
          </div>
          <div className="rounded-full border border-fuchsia-500/30 bg-fuchsia-500/10 px-3 py-1 text-[11px] font-medium text-fuchsia-300">
            Mode D · Agent orchestrator
          </div>
        </div>
      </div>

      <div className="mb-4 flex gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-1">
        <button
          onClick={() => setSubTab('tools')}
          className={`rounded-lg px-3 py-2 text-sm font-medium transition ${subTab === 'tools' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
        >
          Tool prompts
        </button>
        <button
          onClick={() => setSubTab('workflow')}
          className={`rounded-lg px-3 py-2 text-sm font-medium transition ${subTab === 'workflow' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
        >
          Workflow map
        </button>
      </div>

      {subTab === 'tools' ? (
        <div className="space-y-3">
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h4 className="text-sm font-semibold text-white">Copy-pasteable tool cards</h4>
                <p className="mt-1 text-xs text-slate-400">
                  These descriptions are sourced from the backend agent tool schemas and system prompt, so they match the implementation more closely.
                </p>
              </div>
              <button
                onClick={() => handleCopy('system-prompt', systemPrompt)}
                className="rounded-md border border-slate-700 px-2.5 py-1 text-[11px] text-slate-300 hover:border-slate-500 hover:text-white"
              >
                {copiedLabel === 'system-prompt' ? 'Copied' : 'Copy system prompt'}
              </button>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            {tools.map((tool) => (
              <div key={tool.name} className="rounded-xl border border-slate-800 bg-[var(--color-bg)] p-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-white">{tool.name}</p>
                    <p className="mt-1 text-[11px] uppercase tracking-[0.2em] text-slate-500">{tool.when}</p>
                  </div>
                  <button
                    onClick={() => setSelectedTool(tool)}
                    className="rounded-md border border-indigo-500/25 bg-indigo-500/10 px-2.5 py-1 text-[11px] font-medium text-indigo-300 hover:bg-indigo-500/20"
                  >
                    View prompt
                  </button>
                </div>
                <p className="mt-3 text-sm leading-6 text-slate-300">{tool.description}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {tool.requiredTools.map((req) => (
                    <span key={req} className="rounded-full border border-slate-700 bg-slate-900/70 px-2 py-1 text-[10px] text-slate-400">
                      {req}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
            <h4 className="text-sm font-semibold text-white">Detailed document processing workflow</h4>
            <p className="mt-1 text-xs text-slate-400">
              This view breaks the run into decision points, agent tools, and storage destinations so the path is explicit.
            </p>
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
              <div className="flex items-center justify-between">
                <h5 className="text-sm font-semibold text-white">Execution path</h5>
                <span className="text-[11px] text-slate-500">agent-driven branching</span>
              </div>
              <div className="mt-4 space-y-3">
                {[
                  {
                    title: '1. Intake + inspection',
                    tools: ['inspect_document'],
                    decision: 'Always first. The agent checks format, page count, OCR signal, tables, images, and text extractability.',
                    output: 'Produces the inspection payload that decides the parser route.',
                  },
                  {
                    title: '2. Parser selection',
                    tools: ['parse_pdf_native', 'parse_with_docling', 'parse_with_vision_ocr', 'parse_office_document'],
                    decision: 'If the document is born-digital and text-extractable → parse_pdf_native. If scanned or table-heavy → parse_with_docling. If fully scanned / broken-font → parse_with_vision_ocr. If DOCX/PPTX/XLSX/HTML → parse_office_document.',
                    output: 'Creates parser_payload, text_blocks, tables, and images in cache.',
                  },
                  {
                    title: '3. Chunking',
                    tools: ['chunk_text'],
                    decision: 'Only after a parser has populated text_blocks. Chunker creates searchable chunks with heading awareness and overlap.',
                    output: 'Writes chunks into the cache for downstream embedding and retrieval.',
                  },
                  {
                    title: '4. Enrichment branches',
                    tools: ['describe_tables', 'caption_images', 'store_tables_sql', 'extract_entities'],
                    decision: 'If tables exist → describe_tables. If visuals are meaningful → caption_images. If structured tables are present → store_tables_sql. If prose is rich → extract_entities.',
                    output: 'Adds table summaries, image OCR/captions, SQL tables, and graph entities.',
                  },
                  {
                    title: '5. Embedding + indexing',
                    tools: ['embed_and_index'],
                    decision: 'Runs after chunk_text and uses the chunk cache to embed dense vectors and push them to Qdrant.',
                    output: 'Makes the document semantically searchable.',
                  },
                  {
                    title: '6. Finalization',
                    tools: ['finalize'],
                    decision: 'The loop ends here. The agent emits a short summary of what it ingested and what it skipped.',
                    output: 'Completes the run and preserves the audit trail.',
                  },
                ].map((step) => (
                  <div key={step.title} className="rounded-lg border border-slate-800 bg-[var(--color-bg)] p-3">
                    <p className="text-sm font-semibold text-white">{step.title}</p>
                    <p className="mt-2 text-xs leading-6 text-slate-400">{step.decision}</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {step.tools.map((tool) => (
                        <span key={tool} className="rounded-full border border-slate-700 bg-slate-900/70 px-2 py-1 text-[10px] text-slate-400">
                          {tool}
                        </span>
                      ))}
                    </div>
                    <p className="mt-2 text-[11px] text-slate-500">Output: {step.output}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
              <h5 className="text-sm font-semibold text-white">Storage map</h5>
              <div className="mt-4 space-y-3 text-sm text-slate-300">
                <div className="rounded-lg border border-slate-800 bg-[var(--color-bg)] p-3">
                  <p className="font-semibold text-white">Dense chunks</p>
                  <p className="mt-1 text-xs leading-6 text-slate-400">Tool: embed_and_index. Stored in Qdrant as dense vector embeddings using text-embedding-3-large. Used for semantic similarity search.</p>
                </div>
                <div className="rounded-lg border border-slate-800 bg-[var(--color-bg)] p-3">
                  <p className="font-semibold text-white">Sparse keyword index</p>
                  <p className="mt-1 text-xs leading-6 text-slate-400">Tool: embed_and_index (via the BM25-style index path). Stored in memory as a sparse keyword index for exact-match retrieval such as IDs, codes, and reference numbers.</p>
                </div>
                <div className="rounded-lg border border-slate-800 bg-[var(--color-bg)] p-3">
                  <p className="font-semibold text-white">Tables</p>
                  <p className="mt-1 text-xs leading-6 text-slate-400">Tool: store_tables_sql. Stored in per-job SQLite databases. Each table is indexed with its own SQL table and typed columns for exact numeric and aggregate queries.</p>
                </div>
                <div className="rounded-lg border border-slate-800 bg-[var(--color-bg)] p-3">
                  <p className="font-semibold text-white">Graph entities</p>
                  <p className="mt-1 text-xs leading-6 text-slate-400">Tool: extract_entities. Stored as a NetworkX knowledge graph with entities and relationships linked back to chunks.</p>
                </div>
                <div className="rounded-lg border border-slate-800 bg-[var(--color-bg)] p-3">
                  <p className="font-semibold text-white">Table summaries / chunk enrichment</p>
                  <p className="mt-1 text-xs leading-6 text-slate-400">Tool: describe_tables and caption_images. These add summary chunks for tables and OCR-derived content so they can be retrieved semantically as additional chunks.</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {selectedTool && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-2xl rounded-2xl border border-slate-700 bg-[var(--color-surface)] p-4 shadow-2xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-white">{selectedTool.name}</p>
                <p className="mt-1 text-xs text-slate-400">{selectedTool.description}</p>
              </div>
              <button onClick={() => setSelectedTool(null)} className="text-sm text-slate-400 hover:text-white">Close</button>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <div className="rounded-lg border border-slate-800 bg-[var(--color-bg)] p-3">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Required tools</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {selectedTool.requiredTools.length === 0 ? (
                    <span className="text-sm text-slate-400">None — this is the entry-point tool.</span>
                  ) : (
                    selectedTool.requiredTools.map((req) => (
                      <span key={req} className="rounded-full border border-slate-700 bg-slate-900/70 px-2 py-1 text-[10px] text-slate-400">
                        {req}
                      </span>
                    ))
                  )}
                </div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-[var(--color-bg)] p-3">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Actual backend tool text</p>
                <p className="mt-2 text-sm leading-6 text-slate-300">{selectedTool.prompt}</p>
              </div>
            </div>

            <div className="mt-4 rounded-lg border border-slate-800 bg-[var(--color-bg)] p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Agent config snippet</p>
                <div className="flex gap-2">
                  <button onClick={() => handleCopy(`${selectedTool.name}:prompt`, selectedTool.prompt)} className="rounded-md border border-slate-700 px-2.5 py-1 text-[11px] text-slate-300 hover:border-slate-500 hover:text-white">
                    {copiedLabel === `${selectedTool.name}:prompt` ? 'Copied' : 'Copy prompt'}
                  </button>
                  <button onClick={() => handleCopy(`${selectedTool.name}:config`, selectedTool.config)} className="rounded-md border border-slate-700 px-2.5 py-1 text-[11px] text-slate-300 hover:border-slate-500 hover:text-white">
                    {copiedLabel === `${selectedTool.name}:config` ? 'Copied' : 'Copy config'}
                  </button>
                </div>
              </div>
              <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-lg bg-slate-950/80 p-3 text-[11px] leading-5 text-slate-300">{selectedTool.config}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
