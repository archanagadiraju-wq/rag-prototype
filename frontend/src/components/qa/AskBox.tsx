import { useEffect, useRef, useState } from 'react'

// ── Types matching the /api/jobs/<id>/ask response ────────────────────────────

interface RetrievedChunk {
  chunk_id?: string | null
  text?: string
  score?: number
  page?: number | null
  heading?: string | null
}

interface AskResponse {
  question: string
  answer: string
  input_tokens: number
  output_tokens: number
  cost_usd: number
  latency_ms: number
  confidence: number
  confidence_label: string
  context_chunks: number
  retrieved: RetrievedChunk[]
  system_prompt: string
  user_prompt: string
  judge_score?: number | null
  judge_verdict?: string | null
  judge_rationale?: string | null
  error?: string
}

interface QAEntry {
  id: number
  question: string
  status: 'loading' | 'done' | 'error'
  response?: AskResponse
  error?: string
  pipeline: 'custom' | 'docling'
}

// ── Verdict styling, matching the Stage 12 viz ────────────────────────────────

const VERDICT_STYLE: Record<string, { bg: string; border: string; text: string }> = {
  correct:     { bg: 'bg-emerald-900/30', border: 'border-emerald-600/40', text: 'text-emerald-300' },
  partial:     { bg: 'bg-amber-900/30',   border: 'border-amber-600/40',   text: 'text-amber-300'   },
  unsupported: { bg: 'bg-orange-900/30',  border: 'border-orange-600/40',  text: 'text-orange-300'  },
  incorrect:   { bg: 'bg-red-900/30',     border: 'border-red-600/40',     text: 'text-red-300'     },
  unknown:     { bg: 'bg-slate-800/60',   border: 'border-slate-600/40',   text: 'text-slate-400'   },
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const s = VERDICT_STYLE[verdict] ?? VERDICT_STYLE.unknown
  return (
    <div className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10px] font-semibold ${s.bg} ${s.border} ${s.text}`}>
      <span className="text-[9px]">⚖</span>
      {verdict}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function AskBox({ jobId, pipeline }: { jobId: string | null; pipeline: 'custom' | 'docling' }) {
  const [question, setQuestion] = useState('')
  const [entries, setEntries] = useState<QAEntry[]>([])
  const [submitting, setSubmitting] = useState(false)
  const nextId = useRef(1)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new entry
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [entries.length])

  async function submit() {
    const q = question.trim()
    if (!q || !jobId || submitting) return
    const id = nextId.current++
    const placeholder: QAEntry = { id, question: q, status: 'loading', pipeline }
    setEntries((prev) => [...prev, placeholder])
    setQuestion('')
    setSubmitting(true)

    try {
      const res = await fetch(`/api/jobs/${jobId}/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, pipeline }),
      })
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}))
        setEntries((prev) =>
          prev.map((e) => e.id === id ? { ...e, status: 'error', error: detail.detail || res.statusText } : e),
        )
      } else {
        const data: AskResponse = await res.json()
        setEntries((prev) => prev.map((e) => e.id === id ? { ...e, status: 'done', response: data } : e))
      }
    } catch (exc: unknown) {
      const msg = exc instanceof Error ? exc.message : 'request failed'
      setEntries((prev) => prev.map((e) => e.id === id ? { ...e, status: 'error', error: msg } : e))
    } finally {
      setSubmitting(false)
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  if (!jobId) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-600 text-xs">
        No active job — ingest a document first.
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Scrollable Q&A history */}
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
        {entries.length === 0 ? (
          <div className="text-xs text-slate-500 px-2 py-4 leading-relaxed">
            <p className="font-medium text-slate-400 mb-2">Ask anything about this document.</p>
            <p>Examples for the financial spreadsheet:</p>
            <ul className="mt-1.5 space-y-0.5 ml-3 text-slate-600">
              <li>• "What is the projected ARR for end of year 2026?"</li>
              <li>• "How does the bull case compare to the bear case?"</li>
              <li>• "Who are the headcount additions in Q3?"</li>
            </ul>
            <p className="mt-3 text-slate-600">Each answer is grounded in the document, judged by a second AI for correctness, and shows the chunks it came from.</p>
          </div>
        ) : (
          entries.map((entry) => <Bubble key={entry.id} entry={entry} />)
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-[var(--color-border)] p-2.5 bg-[var(--color-surface)]">
        <div className="flex gap-2 items-end">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask anything about this document…"
            disabled={submitting}
            rows={2}
            className="flex-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-lg px-2.5 py-1.5 text-xs text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-indigo-500/50"
          />
          <button
            onClick={submit}
            disabled={!question.trim() || submitting}
            className="px-3 py-1.5 rounded-lg bg-indigo-500/20 hover:bg-indigo-500/30 disabled:opacity-40 disabled:cursor-not-allowed border border-indigo-500/40 text-indigo-300 text-xs font-medium transition-colors h-fit"
          >
            {submitting ? '…' : 'Ask'}
          </button>
        </div>
        <p className="text-[10px] text-slate-600 mt-1 px-1">Enter to send · Shift+Enter for newline</p>
      </div>
    </div>
  )
}

// ── A single Q&A bubble ───────────────────────────────────────────────────────

function Bubble({ entry }: { entry: QAEntry }) {
  const [showChunks, setShowChunks] = useState(false)
  const [showPrompt, setShowPrompt] = useState(false)

  return (
    <div className="space-y-1.5">
      {/* User question */}
      <div className="flex justify-end">
        <div className="max-w-[85%] px-3 py-1.5 rounded-lg bg-indigo-500/15 border border-indigo-500/30 text-xs text-indigo-100">
          {entry.question}
        </div>
      </div>

      {/* Loading / error / answer */}
      {entry.status === 'loading' && (
        <div className="flex">
          <div className="px-3 py-1.5 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-xs text-slate-500 italic">
            thinking…
          </div>
        </div>
      )}

      {entry.status === 'error' && (
        <div className="flex">
          <div className="px-3 py-1.5 rounded-lg bg-red-900/20 border border-red-700/40 text-xs text-red-300">
            error: {entry.error}
          </div>
        </div>
      )}

      {entry.status === 'done' && entry.response && (
        <div className="space-y-1.5">
          <div className="max-w-[95%]">
            <div className="px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-xs text-slate-200 leading-relaxed whitespace-pre-wrap">
              {entry.response.answer}
            </div>
          </div>

          {/* Footer chips: verdict, cost, latency, chunks toggle */}
          <div className="flex items-center gap-2 flex-wrap text-[10px]">
            {entry.response.judge_score != null && entry.response.judge_verdict && (
              <VerdictBadge verdict={entry.response.judge_verdict} />
            )}
            <span className="text-slate-500">
              {entry.response.context_chunks} chunks ·{' '}
              {entry.response.latency_ms < 1000
                ? `${entry.response.latency_ms.toFixed(0)}ms`
                : `${(entry.response.latency_ms / 1000).toFixed(1)}s`}
            </span>
            <span className="text-emerald-500/80">
              ${(entry.response.cost_usd * 100).toFixed(4)}¢
            </span>
            <button
              onClick={() => setShowChunks((s) => !s)}
              className="text-indigo-400 hover:text-indigo-300 underline-offset-2 hover:underline"
            >
              {showChunks ? 'hide chunks' : `show ${entry.response.retrieved?.length ?? 0} chunks`}
            </button>
            <button
              onClick={() => setShowPrompt((s) => !s)}
              className="text-slate-500 hover:text-slate-300 underline-offset-2 hover:underline"
            >
              {showPrompt ? 'hide prompt' : 'view prompt'}
            </button>
          </div>

          {/* Judge rationale */}
          {entry.response.judge_rationale && (
            <p className="text-[10px] text-slate-500 italic px-1 leading-snug">
              ⚖ {entry.response.judge_rationale}
            </p>
          )}

          {/* Retrieved chunks (collapsible) */}
          {showChunks && entry.response.retrieved && (
            <div className="space-y-1 pl-2 border-l-2 border-slate-700">
              {entry.response.retrieved.map((c, i) => (
                <div key={i} className="text-[10px]">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-slate-600">#{i + 1}</span>
                    {c.heading && <span className="text-slate-500">{c.heading}</span>}
                    {c.page != null && <span className="text-slate-600">p.{c.page}</span>}
                    <span className="text-slate-600 font-mono ml-auto">{(c.score ?? 0).toFixed(3)}</span>
                  </div>
                  <p className="text-slate-400 leading-snug pl-3">{c.text}</p>
                </div>
              ))}
            </div>
          )}

          {/* Raw prompt (collapsible) */}
          {showPrompt && (
            <details open className="text-[10px]">
              <summary className="cursor-pointer text-slate-500 hover:text-slate-300">prompt sent to model</summary>
              <div className="mt-1 space-y-2">
                <div>
                  <p className="text-indigo-400 uppercase tracking-wider font-medium mb-0.5">system</p>
                  <pre className="whitespace-pre-wrap font-mono text-slate-300 bg-[var(--color-bg)] border border-[var(--color-border)] rounded p-2">{entry.response.system_prompt}</pre>
                </div>
                <div>
                  <p className="text-emerald-400 uppercase tracking-wider font-medium mb-0.5">user · {entry.response.user_prompt.length.toLocaleString()} chars</p>
                  <pre className="whitespace-pre-wrap font-mono text-slate-300 bg-[var(--color-bg)] border border-[var(--color-border)] rounded p-2 max-h-48 overflow-y-auto">{entry.response.user_prompt}</pre>
                </div>
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  )
}
