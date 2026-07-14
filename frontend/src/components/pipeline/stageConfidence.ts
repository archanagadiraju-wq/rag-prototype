import type { StageState } from '../../hooks/usePipelineStore'
import { computeExtractionConfidence } from '../stages/ParserViz'

export interface StageConfidence {
  score: number
  source: 'format-detect' | 'content-intel' | 'parser' | 'verification' | 'unknown'
}

export function getStageConfidence(stage: StageState): StageConfidence | null {
  const payload: any = stage.payload ?? {}
  const toolResult: any = payload.tool_result ?? {}

  if (payload.confidence != null) {
    return { score: Number(payload.confidence), source: 'format-detect' }
  }
  if (payload.doc_type_confidence != null) {
    return { score: Number(payload.doc_type_confidence), source: 'content-intel' }
  }
  if (toolResult.confidence != null) {
    return { score: Number(toolResult.confidence), source: 'parser' }
  }
  if (toolResult.doc_type_confidence != null) {
    return { score: Number(toolResult.doc_type_confidence), source: 'content-intel' }
  }
  if (toolResult.parser_used || toolResult.parser || toolResult.text_blocks) {
    return { score: computeExtractionConfidence(toolResult).score, source: 'parser' }
  }
  if (payload.parser_used || payload.parser || payload.text_blocks) {
    return { score: computeExtractionConfidence(payload).score, source: 'parser' }
  }
  if (stage.verification?.l2_score != null) {
    return { score: stage.verification.l2_score, source: 'verification' }
  }
  return null
}
