import React from 'react'
import { render, screen } from '@testing-library/react'
import { expect, vi, describe, it } from 'vitest'
import '@testing-library/jest-dom/vitest'

// Mock the pipeline store to return a single completed agent stage
vi.mock('../../../hooks/usePipelineStore', () => {
  return {
    usePipelineStore: () => ({
      selectedStage: 1,
      stages: [
        {
          id: 1,
          name: 'agent.parse_with_docling',
          status: 'completed',
          duration_ms: 420,
          payload: {
            tool: 'parse_with_docling',
            tool_input: { do_ocr: true },
            tool_result: {
              parser: 'docling-2.x',
              page_count: 4,
              word_count: 333,
              chunk_count: 5,
              ocr_used: true,
            },
          },
          verification: { l1_checks: [] },
        },
      ],
    }),
  }
})

// Import after mock so the module uses the mocked hook
import { StageDetail } from '../StageDetail'

describe('StageDetail', () => {
  it('renders agent tool stage payload and result data', async () => {
    render(<StageDetail />)

    expect(await screen.findByText(/tool called/i)).toBeInTheDocument()
    expect((await screen.findAllByText(/parse_with_docling/)).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/"do_ocr": true/)).toBeInTheDocument()
    expect(screen.getByText(/docling-2.x/)).toBeInTheDocument()
    expect(screen.getByText(/page_count/)).toBeInTheDocument()
  })
})
