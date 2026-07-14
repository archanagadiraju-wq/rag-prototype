import { create } from 'zustand'
import { persist, createJSONStorage, type StateStorage } from 'zustand/middleware'
import type { StageEvent, PipelineMode } from '../types/events'

// Debounced localStorage wrapper. Zustand's persist middleware writes on every
// `set()` call — without debouncing, a stage emitting 50 events/sec means 50
// synchronous JSON.stringify + localStorage.setItem calls per second. Each can
// run 10–100ms for large state. That alone can hang the tab. We coalesce
// writes within a 500ms window — we lose at most 500ms of state on a hard
// crash, which is fine: rehydration uses backend WS replay as the source of
// truth anyway.
function debouncedLocalStorage(ms: number): StateStorage {
  let pending: Record<string, string> = {}
  let timer: number | undefined
  const flush = () => {
    for (const [k, v] of Object.entries(pending)) {
      try { localStorage.setItem(k, v) } catch { /* quota exceeded — ignore */ }
    }
    pending = {}
    timer = undefined
  }
  return {
    getItem: (name) => localStorage.getItem(name),
    setItem: (name, value) => {
      pending[name] = value
      if (timer == null) timer = window.setTimeout(flush, ms)
    },
    removeItem: (name) => {
      delete pending[name]
      localStorage.removeItem(name)
    },
  }
}

export type StageStatus = 'idle' | 'started' | 'running' | 'completed' | 'error'

export interface StageState {
  id: number
  name: string
  status: StageStatus
  duration_ms?: number
  payload?: Record<string, unknown>
  verification?: StageEvent['verification']
  events: StageEvent[]
}

export interface RunState {
  jobId: string
  filename: string
  pipeline: PipelineMode
  stages: StageState[]              // for custom/docling single-pipeline runs
  customStages: StageState[]        // for compare mode
  doclingStages: StageState[]       // for compare mode
  wsLog: StageEvent[]               // per-job event log
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  startedAt: number
  finishedAt?: number
  progressDone: number              // count of completed stages (for single pipeline)
  progressTotal: number             // total stage count (for single pipeline)
}

const CUSTOM_STAGE_NAMES = [
  'Intake', 'Format Detection', 'Format Parser', 'Content Intelligence',
  'Smart Chunking', 'Multi-Modal', 'Embedding', 'Metadata',
  'Knowledge Graph', 'Vector Store', 'RAG Ready', 'LLM Answer',
]

const DOCLING_STAGE_NAMES = [
  'Intake', 'Docling Unified Parse', 'Multi-Modal', 'Embedding',
  'Metadata', 'Knowledge Graph', 'Vector Store', 'RAG Ready', 'LLM Answer',
]

function makeStages(names: string[]): StageState[] {
  return names.map((name, i) => ({ id: i + 1, name, status: 'idle' as StageStatus, events: [] }))
}

function stagesForMode(mode: PipelineMode): StageState[] {
  // Agent mode discovers its stages dynamically (one per tool the agent decides to call),
  // so start with an empty list and let applyEvent append them on the fly.
  if (mode === 'agent') return []
  return makeStages(mode === 'docling' ? DOCLING_STAGE_NAMES : CUSTOM_STAGE_NAMES)
}

// Caps on per-stage and per-run event accumulation. Long stages (Docling, large
// embedding batches) emit a heartbeat every 30s — over a 10-min stage that's
// only 20 events, but a misbehaving stage that emits an event per second would
// produce 600. Combined with `wsLog`, an unbounded run can balloon to MB
// of in-memory state and trigger React re-render storms.
const MAX_EVENTS_PER_STAGE = 50
const MAX_WS_LOG = 500

function applyEvent(stages: StageState[], event: StageEvent): StageState[] {
  const existing = stages.find((s) => s.id === event.stage_id)
  if (!existing) {
    // Dynamic stage (agent mode emits new stage_ids as it calls tools)
    return [
      ...stages,
      {
        id: event.stage_id,
        name: event.stage_name,
        status: event.status as StageStatus,
        duration_ms: event.duration_ms,
        payload: event.status === 'completed' ? event.payload : undefined,
        verification: event.verification,
        events: [event],
      },
    ]
  }
  return stages.map((s) => {
    if (s.id !== event.stage_id) return s
    // Keep only the last MAX_EVENTS_PER_STAGE — sliding window so we always
    // retain the most recent heartbeats + the completion event.
    const nextEvents = s.events.length >= MAX_EVENTS_PER_STAGE
      ? [...s.events.slice(-(MAX_EVENTS_PER_STAGE - 1)), event]
      : [...s.events, event]
    return {
      ...s,
      name: event.stage_name,  // allow rename (agent picks tool name dynamically)
      status: event.status as StageStatus,
      duration_ms: event.duration_ms ?? s.duration_ms,
      payload: event.status === 'completed' ? event.payload : s.payload,
      verification: event.verification ?? s.verification,
      events: nextEvents,
    }
  })
}

function deriveStatus(run: RunState): RunState['status'] {
  const allStages = run.pipeline === 'compare'
    ? [...run.customStages, ...run.doclingStages]
    : run.stages
  // The backend emits a sentinel stage with name='cancelled' (status='error')
  // when DELETE /api/jobs/{id} fires. Treat that as a distinct state, not
  // a real failure — otherwise the UI shows red "FAILED" for a user cancel.
  if (allStages.some((s) => s.name === 'cancelled')) return 'cancelled'
  if (allStages.some((s) => s.status === 'error')) return 'failed'
  const done = allStages.filter((s) => s.status === 'completed').length
  if (done === allStages.length) return 'completed'
  if (done > 0 || allStages.some((s) => s.status === 'running' || s.status === 'started')) return 'running'
  return run.status
}

function countDone(stages: StageState[]): number {
  return stages.filter((s) => s.status === 'completed').length
}

interface PipelineStore {
  mode: PipelineMode
  setMode: (m: PipelineMode) => void

  // Multi-job tracking
  runs: Record<string, RunState>
  jobOrder: string[]
  activeJobId: string | null
  setActiveJobId: (id: string | null) => void
  addRun: (jobId: string, filename: string, pipeline: PipelineMode) => void
  removeRun: (jobId: string) => void
  resetAll: () => void

  // ── Backward-compat views (mirror active run; kept so existing components don't change) ──
  jobId: string | null
  stages: StageState[]
  customStages: StageState[]
  doclingStages: StageState[]
  wsLog: StageEvent[]

  selectedStage: number | null
  selectedPipeline: 'custom' | 'docling'
  setSelectedStage: (id: number | null, pipeline?: 'custom' | 'docling') => void

  // Event ingestion
  handleEvent: (event: StageEvent) => void

  // Legacy single-job reset (kept; resets just the active run)
  resetPipeline: () => void

  // Legacy single-job setter (kept; sets the active job's id)
  setJobId: (id: string | null) => void
}

function emptyLegacy(mode: PipelineMode) {
  return {
    jobId: null,
    stages: stagesForMode(mode),
    customStages: makeStages(CUSTOM_STAGE_NAMES),
    doclingStages: makeStages(DOCLING_STAGE_NAMES),
    wsLog: [],
  }
}

function syncLegacyFromRun(run: RunState | undefined, mode: PipelineMode) {
  if (!run) return emptyLegacy(mode)
  return {
    jobId: run.jobId,
    stages: run.stages,
    customStages: run.customStages,
    doclingStages: run.doclingStages,
    wsLog: run.wsLog,
  }
}

export const usePipelineStore = create<PipelineStore>()(persist((set, get) => ({
  mode: 'agent',
  runs: {},
  jobOrder: [],
  activeJobId: null,
  selectedStage: null,
  selectedPipeline: 'custom',
  ...emptyLegacy('custom'),

  setMode: (mode) => {
    set({ mode, ...emptyLegacy(mode), runs: {}, jobOrder: [], activeJobId: null, selectedStage: null })
  },

  setActiveJobId: (id) => {
    const { runs, mode } = get()
    if (id == null) {
      set({ activeJobId: null, ...emptyLegacy(mode) })
      return
    }
    const run = runs[id]
    set({ activeJobId: id, ...syncLegacyFromRun(run, mode) })
  },

  addRun: (jobId, filename, pipeline) => {
    set((state) => {
      if (state.runs[jobId]) return {}
      const run: RunState = {
        jobId,
        filename,
        pipeline,
        stages: stagesForMode(pipeline),
        customStages: makeStages(CUSTOM_STAGE_NAMES),
        doclingStages: makeStages(DOCLING_STAGE_NAMES),
        wsLog: [],
        status: 'queued',
        startedAt: Date.now(),
        progressDone: 0,
        progressTotal: pipeline === 'docling' ? DOCLING_STAGE_NAMES.length : CUSTOM_STAGE_NAMES.length,
      }
      const newRuns = { ...state.runs, [jobId]: run }
      const newOrder = [...state.jobOrder, jobId]
      const becomesActive = state.activeJobId == null
      return {
        runs: newRuns,
        jobOrder: newOrder,
        activeJobId: becomesActive ? jobId : state.activeJobId,
        ...(becomesActive ? syncLegacyFromRun(run, state.mode) : {}),
      }
    })
  },

  removeRun: (jobId) => {
    set((state) => {
      if (!state.runs[jobId]) return {}
      const { [jobId]: _drop, ...rest } = state.runs
      const newOrder = state.jobOrder.filter((id) => id !== jobId)
      let newActive = state.activeJobId
      if (newActive === jobId) newActive = newOrder[0] ?? null
      return {
        runs: rest,
        jobOrder: newOrder,
        activeJobId: newActive,
        ...syncLegacyFromRun(newActive ? rest[newActive] : undefined, state.mode),
      }
    })
  },

  resetAll: () => {
    const { mode } = get()
    set({ runs: {}, jobOrder: [], activeJobId: null, selectedStage: null, ...emptyLegacy(mode) })
  },

  setSelectedStage: (id, pipeline = 'custom') =>
    set({ selectedStage: id, selectedPipeline: pipeline }),

  handleEvent: (event) =>
    set((state) => {
      // Route to the right run by job_id (always present on backend events)
      const targetJobId = state.runs[event.job_id] ? event.job_id : state.activeJobId
      if (!targetJobId || !state.runs[targetJobId]) return {}

      const run = state.runs[targetJobId]
      // Sliding-window wsLog — keep only the last MAX_WS_LOG events.
      const nextWsLog = run.wsLog.length >= MAX_WS_LOG
        ? [...run.wsLog.slice(-(MAX_WS_LOG - 1)), event]
        : [...run.wsLog, event]
      let next: RunState = { ...run, wsLog: nextWsLog }

      if (event.pipeline === 'custom' && run.pipeline === 'compare') {
        next = { ...next, customStages: applyEvent(run.customStages, event) }
      } else if (event.pipeline === 'docling' && run.pipeline === 'compare') {
        next = { ...next, doclingStages: applyEvent(run.doclingStages, event) }
      } else {
        next = { ...next, stages: applyEvent(run.stages, event) }
      }

      next.progressDone = countDone(next.stages)
      next.status = deriveStatus(next)
      if (next.status === 'completed' && !next.finishedAt) next.finishedAt = Date.now()

      const newRuns = { ...state.runs, [targetJobId]: next }
      const isActive = targetJobId === state.activeJobId
      return {
        runs: newRuns,
        ...(isActive ? syncLegacyFromRun(next, state.mode) : {}),
      }
    }),

  resetPipeline: () => {
    // Reset just the active run's stages (used by single-file legacy code path)
    const { activeJobId, mode } = get()
    if (!activeJobId) {
      set({ ...emptyLegacy(mode), selectedStage: null })
      return
    }
    set((state) => {
      const run = state.runs[activeJobId]
      if (!run) return {}
      const reset: RunState = {
        ...run,
        stages: stagesForMode(run.pipeline),
        customStages: makeStages(CUSTOM_STAGE_NAMES),
        doclingStages: makeStages(DOCLING_STAGE_NAMES),
        wsLog: [],
        status: 'queued',
        progressDone: 0,
        finishedAt: undefined,
      }
      return {
        runs: { ...state.runs, [activeJobId]: reset },
        ...syncLegacyFromRun(reset, state.mode),
        selectedStage: null,
      }
    })
  },

  setJobId: (id) => {
    // Legacy: setJobId now means "make this the active job"; runs[id] must already exist via addRun
    const { setActiveJobId } = get()
    setActiveJobId(id)
  },
}), {
  name: 'rag-prototype:pipeline',
  version: 1,
  storage: createJSONStorage(() => debouncedLocalStorage(500)),
  // Persist only the identity of each job + active selection. Stage state and
  // wsLog are intentionally NOT persisted — the backend WebSocket replays its
  // full buffered event log on every reconnect, so the per-stage UI rebuilds
  // itself naturally after a page reload. Persisting events would also blow
  // past localStorage's ~5MB quota on long-running jobs.
  partialize: (state) => ({
    mode: state.mode,
    activeJobId: state.activeJobId,
    jobOrder: state.jobOrder,
    runs: Object.fromEntries(
      Object.entries(state.runs).map(([id, r]) => [id, {
        jobId: r.jobId,
        filename: r.filename,
        pipeline: r.pipeline,
        stages: stagesForMode(r.pipeline),
        customStages: makeStages(CUSTOM_STAGE_NAMES),
        doclingStages: makeStages(DOCLING_STAGE_NAMES),
        wsLog: [],
        status: 'queued' as const,
        startedAt: r.startedAt,
        progressDone: 0,
        progressTotal: r.progressTotal,
      }]),
    ),
  }),
  onRehydrateStorage: () => (rehydrated) => {
    // After rehydration, mirror the legacy single-job views to whichever
    // job was active when the page unloaded. This is what makes the active
    // run's stages immediately visible (even before WS reconnects).
    if (!rehydrated) return
    rehydrated.mode = 'agent'
    const active = rehydrated.activeJobId ? rehydrated.runs[rehydrated.activeJobId] : undefined
    if (active) {
      const legacy = syncLegacyFromRun(active, rehydrated.mode)
      Object.assign(rehydrated, legacy)
    }
  },
}))
