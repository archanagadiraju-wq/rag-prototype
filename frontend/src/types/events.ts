export interface CheckResult {
  name: string
  passed: boolean
  severity: 'info' | 'warn' | 'fail'
  detail: string
  value?: unknown
  threshold?: unknown
}

export interface VerificationSnapshot {
  l1_checks: CheckResult[]
  l1_pass_rate: number
  l2_score?: number
  l3_report?: L3Report
}

export interface L3RetrievalResult {
  query: string
  recall_at_1: boolean
  recall_at_3: boolean
  recall_at_5: boolean
  reciprocal_rank: number
  top_result_text: string
  top_result_score: number
  gold_found_at_rank: number | null
}

export interface L3Report {
  recall_at_1: number
  recall_at_3: number
  recall_at_5: number
  mrr: number
  per_query: L3RetrievalResult[]
}

export interface RetrievalResult {
  chunk_id: string
  text: string
  dense_score: number
  sparse_score: number
  rrf_score: number
  rerank_score: number
  final_rank: number
}

export interface StageEvent {
  job_id: string
  pipeline: 'custom' | 'docling'
  stage_id: number
  stage_name: string
  status: 'started' | 'running' | 'completed' | 'error'
  timestamp_ms: number
  duration_ms?: number
  progress?: number
  payload: Record<string, unknown>
  verification?: VerificationSnapshot
}

export type PipelineMode = 'custom' | 'docling' | 'compare' | 'agent'

export interface Job {
  job_id: string
  status: 'running' | 'completed' | 'error'
  pipeline: string
  doc_filename: string
  created_at: string
  completed_at?: string
  error?: string
}

export interface DemoDoc {
  id: string
  filename: string
  doc_type: string
  domain: string
  description: string
  has_ground_truth: boolean
}
