import { useState } from 'react'
import type { StageState } from '../../hooks/usePipelineStore'

interface MessagePreview {
  role: string
  kinds: string[]
  preview: string
}

interface TurnTrace {
  turn_input_tokens?: number
  turn_output_tokens?: number
  turn_cache_read_tokens?: number
  turn_cache_create_tokens?: number
  turn_cost_usd?: number
  cumulative_input_tokens?: number
  cumulative_output_tokens?: number
  cumulative_cache_read?: number
  cumulative_cache_create?: number
  stop_reason?: string
  system_prompt?: string
  system_prompt_chars?: number
  tools_available?: string[]
  tool_schemas?: { name: string; description: string }[]
  messages_count?: number
  messages_preview?: MessagePreview[]
}

interface AgentStagePayload {
  reasoning?: string
  tool?: string
  tool_input?: Record<string, unknown>
  tool_result?: Record<string, unknown>
  iteration?: number
  turn?: TurnTrace
}

function fmtTok(n: number | undefined): string {
  if (!n) return '—'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return n.toLocaleString()
}

function fmtCost(usd: number | undefined): string {
  if (!usd) return '—'
  if (usd >= 0.01) return `$${usd.toFixed(4)}`
  return `$${(usd * 100).toFixed(4)}¢`
}

function Section({
  title, accent, children,
}: { title: string; accent: 'indigo' | 'emerald' | 'amber' | 'slate'; children: React.ReactNode }) {
  const colors = {
    indigo:  'border-indigo-500/30  text-indigo-300',
    emerald: 'border-emerald-500/30 text-emerald-300',
    amber:   'border-amber-500/30   text-amber-300',
    slate:   'border-slate-600/40   text-slate-400',
  }
  return (
    <div className={`border rounded-xl ${colors[accent]} bg-[var(--color-bg)]`}>
      <div className={`px-3 py-1.5 border-b ${colors[accent]} bg-slate-900/40 text-[10px] uppercase tracking-wider font-semibold`}>
        {title}
      </div>
      <div className="p-3 text-xs space-y-2">{children}</div>
    </div>
  )
}

function KV({ k, v, mono }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-slate-500 min-w-[110px] text-[11px]">{k}</span>
      <span className={`text-slate-200 ${mono ? 'font-mono text-[11px]' : ''}`}>{v}</span>
    </div>
  )
}

export function AgentTurnViz({ stage }: { stage: StageState }) {
  const p = stage.payload as AgentStagePayload
  const [showMessages, setShowMessages] = useState(false)
  const [showResult, setShowResult] = useState(true)
  const [showSystemPrompt, setShowSystemPrompt] = useState(false)
  const [showToolSchemas, setShowToolSchemas] = useState(false)
  if (!p) return null

  const turn = p.turn
  const result = p.tool_result || {}
  const resultElapsed = (result as { _elapsed_ms?: number })._elapsed_ms
  const resultDisplay = Object.fromEntries(
    Object.entries(result).filter(([k]) => !k.startsWith('_')),
  )

  return (
    <div className="space-y-3">

      {/* ── INPUT CONTEXT ────────────────────────────────────────────────── */}
      {turn && (
        <Section title="Input Context" accent="indigo">
          <KV k="iteration"     v={`turn ${p.iteration}`} />

          {/* System prompt — collapsed by default, click to see full text */}
          <div>
            <KV k="system prompt" v={
              <span>
                cached, {turn.system_prompt_chars?.toLocaleString() ?? '—'} chars
                {turn.system_prompt && (
                  <button
                    onClick={() => setShowSystemPrompt((s) => !s)}
                    className="ml-2 text-indigo-400 hover:text-indigo-300 underline-offset-2 hover:underline text-[10px]"
                  >
                    {showSystemPrompt ? 'hide full text ▲' : 'show full text ▼'}
                  </button>
                )}
              </span>
            } />
            {showSystemPrompt && turn.system_prompt && (
              <pre className="mt-1.5 ml-[120px] whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-slate-300 bg-slate-900/60 border border-slate-700/40 rounded-lg p-2.5 max-h-[400px] overflow-y-auto">
                {turn.system_prompt}
              </pre>
            )}
          </div>

          {/* Tool schemas — collapsed by default */}
          <div>
            <KV k="tools" v={
              <span>
                <span className="font-mono text-[11px]">{turn.tools_available?.length ?? 0} available</span>
                {turn.tool_schemas && (
                  <button
                    onClick={() => setShowToolSchemas((s) => !s)}
                    className="ml-2 text-indigo-400 hover:text-indigo-300 underline-offset-2 hover:underline text-[10px]"
                  >
                    {showToolSchemas ? 'hide tool schemas ▲' : 'show tool schemas ▼'}
                  </button>
                )}
              </span>
            } />
            {!showToolSchemas && (
              <p className="ml-[120px] text-[10px] font-mono text-slate-500 mt-0.5">
                [{turn.tools_available?.join(', ')}]
              </p>
            )}
            {showToolSchemas && turn.tool_schemas && (
              <div className="mt-1.5 ml-[120px] space-y-1.5 bg-slate-900/60 border border-slate-700/40 rounded-lg p-2.5 max-h-[400px] overflow-y-auto">
                {turn.tool_schemas.map((t) => (
                  <div key={t.name} className="text-[10px]">
                    <span className="font-mono text-emerald-400 font-semibold">{t.name}</span>
                    <p className="text-slate-400 leading-snug mt-0.5 pl-2 border-l border-slate-700">
                      {t.description}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <KV k="messages" v={
            <span>
              {turn.messages_count} in history{' '}
              {turn.messages_preview && turn.messages_preview.length > 0 && (
                <button
                  onClick={() => setShowMessages((s) => !s)}
                  className="ml-2 text-indigo-400 hover:text-indigo-300 underline-offset-2 hover:underline text-[10px]"
                >
                  {showMessages ? 'hide history ▲' : `show history (${turn.messages_preview.length}) ▼`}
                </button>
              )}
            </span>
          } />
          {showMessages && turn.messages_preview && (
            <div className="mt-2 space-y-1 pl-3 border-l border-slate-700">
              {turn.messages_preview.map((m, i) => (
                <div key={i} className="text-[10px] flex gap-2">
                  <span className="text-slate-600 w-4">[{i}]</span>
                  <span className={`font-medium ${m.role === 'user' ? 'text-emerald-400' : 'text-indigo-400'}`}>
                    {m.role}
                  </span>
                  <span className="text-slate-500 font-mono">[{m.kinds.join(',')}]</span>
                  <span className="text-slate-400 truncate flex-1" title={m.preview}>{m.preview}</span>
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* ── AGENT RESPONSE ───────────────────────────────────────────────── */}
      <Section title="Agent Response" accent="emerald">
        {p.reasoning && (
          <div>
            <p className="text-[10px] text-slate-500 mb-1">reasoning</p>
            <p className="text-slate-300 italic whitespace-pre-wrap text-[11px] leading-relaxed">
              {p.reasoning}
            </p>
          </div>
        )}
        <KV k="tool called" v={
          <span className="font-mono text-emerald-300">
            {p.tool}({JSON.stringify(p.tool_input || {})})
          </span>
        } />
        {turn?.stop_reason && <KV k="stop reason" v={turn.stop_reason} mono />}
      </Section>

      {/* ── METRICS THIS TURN ────────────────────────────────────────────── */}
      {turn && (
        <Section title="Metrics — This Turn" accent="amber">
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider">tokens this turn</p>
              <div className="flex items-center gap-3 text-[11px] font-mono">
                <span><span className="text-slate-500">in </span>{fmtTok(turn.turn_input_tokens)}</span>
                <span><span className="text-slate-500">out </span>{fmtTok(turn.turn_output_tokens)}</span>
              </div>
              <div className="flex items-center gap-3 text-[11px] font-mono">
                <span title="Tokens served from prompt cache at 10% cost">
                  <span className="text-slate-500">cache_read </span>
                  <span className="text-emerald-400">{fmtTok(turn.turn_cache_read_tokens)}</span>
                </span>
                <span title="Tokens written to cache at 1.25x cost (first turn only)">
                  <span className="text-slate-500">cache_create </span>
                  <span className="text-indigo-400">{fmtTok(turn.turn_cache_create_tokens)}</span>
                </span>
              </div>
              <div className="text-[11px] font-mono pt-1">
                <span className="text-slate-500">turn cost </span>
                <span className="text-amber-300 font-semibold">{fmtCost(turn.turn_cost_usd)}</span>
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider">cumulative (job total)</p>
              <div className="flex items-center gap-3 text-[11px] font-mono">
                <span><span className="text-slate-500">in </span>{fmtTok(turn.cumulative_input_tokens)}</span>
                <span><span className="text-slate-500">out </span>{fmtTok(turn.cumulative_output_tokens)}</span>
              </div>
              <div className="flex items-center gap-3 text-[11px] font-mono">
                <span>
                  <span className="text-slate-500">cache_read </span>
                  <span className="text-emerald-400">{fmtTok(turn.cumulative_cache_read)}</span>
                </span>
                <span>
                  <span className="text-slate-500">cache_create </span>
                  <span className="text-indigo-400">{fmtTok(turn.cumulative_cache_create)}</span>
                </span>
              </div>
            </div>
          </div>
          {(turn.cumulative_cache_read ?? 0) === 0 && (turn.turn_cache_read_tokens ?? 0) === 0 && (
            <p className="text-[10px] text-slate-600 mt-1 leading-snug">
              💡 Cache is still being seeded (first 1-3 turns). Subsequent turns
              should show <span className="text-emerald-400 font-mono">cache_read</span> rising
              as the system+tools prefix becomes hot.
            </p>
          )}
        </Section>
      )}

      {/* ── TOOL EXECUTION ───────────────────────────────────────────────── */}
      <Section title="Tool Execution" accent="slate">
        <KV k="tool" v={<span className="font-mono">{p.tool}</span>} />
        <KV k="input"    v={
          <pre className="font-mono text-[11px] text-slate-300 bg-slate-900/50 rounded px-2 py-1 mt-0.5">
            {JSON.stringify(p.tool_input || {}, null, 2)}
          </pre>
        } />
        {resultElapsed != null && (
          <KV k="elapsed" v={<span className="font-mono text-slate-300">{resultElapsed.toFixed(0)}ms</span>} />
        )}
        <div>
          <button
            onClick={() => setShowResult((s) => !s)}
            className="text-[11px] text-slate-500 hover:text-slate-300 underline-offset-2 hover:underline"
          >
            {showResult ? 'hide result' : 'show result'}
          </button>
          {showResult && (
            <pre className="mt-1 font-mono text-[11px] text-slate-300 bg-slate-900/50 rounded px-2 py-1.5 overflow-auto max-h-64">
              {JSON.stringify(resultDisplay, null, 2)}
            </pre>
          )}
        </div>
      </Section>
    </div>
  )
}
