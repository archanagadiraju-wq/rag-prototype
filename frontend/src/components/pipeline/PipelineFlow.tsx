import { useCallback, memo } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeProps,
  Position,
  Handle,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { usePipelineStore, type StageState } from '../../hooks/usePipelineStore'

const STATUS_BG: Record<string, string> = {
  idle: '#1a1d27',
  started: '#312e81',
  running: '#1e1b4b',
  completed: '#052e16',
  error: '#450a0a',
}

const STATUS_BORDER: Record<string, string> = {
  idle: '#2d3148',
  started: '#6366f1',
  running: '#818cf8',
  completed: '#22c55e',
  error: '#ef4444',
}

type StageNodeData = { stage: StageState }

const StageNode = memo(({ data }: NodeProps & { data: StageNodeData }) => {
  const { stage } = data
  const borderColor = STATUS_BORDER[stage.status] ?? '#2d3148'
  const bgColor = STATUS_BG[stage.status] ?? '#1a1d27'

  return (
    <div style={{ position: 'relative' }}>
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: borderColor, border: 'none' }}
      />
      <div
        style={{
          background: bgColor,
          border: `1.5px solid ${borderColor}`,
          borderRadius: 12,
          padding: '8px 16px',
          minWidth: 140,
          textAlign: 'center',
          color: '#f1f5f9',
          fontFamily: 'system-ui, sans-serif',
          fontSize: 13,
          fontWeight: 500,
        }}
      >
        <div style={{ fontSize: 10, color: '#64748b', marginBottom: 2 }}>{stage.id}</div>
        <div>{stage.name}</div>
        {stage.duration_ms != null && (
          <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>
            {stage.duration_ms.toFixed(0)}ms
          </div>
        )}
      </div>
      <Handle
        type="source"
        position={Position.Right}
        style={{ background: borderColor, border: 'none' }}
      />
    </div>
  )
})
StageNode.displayName = 'StageNode'

const nodeTypes = { stageNode: StageNode }

export function PipelineFlow({ pipelineOverride }: { pipelineOverride?: 'custom' | 'docling' } = {}) {
  const { stages, customStages, doclingStages, setSelectedStage } = usePipelineStore()
  const displayStages = pipelineOverride === 'custom' ? customStages
    : pipelineOverride === 'docling' ? doclingStages
    : stages

  const nodes: Node[] = displayStages.map((stage, i) => ({
    id: String(stage.id),
    type: 'stageNode',
    position: { x: (i % 5) * 200, y: Math.floor(i / 5) * 120 },
    data: { stage } as StageNodeData,
  }))

  const edges: Edge[] = displayStages.slice(0, -1).map((_, i) => ({
    id: `e${i + 1}-${i + 2}`,
    source: String(i + 1),
    target: String(i + 2),
    style: { stroke: '#2d3148' },
    animated: displayStages[i + 1].status === 'started' || displayStages[i + 1].status === 'running',
  }))

  const onNodeClick = useCallback(
    (_evt: React.MouseEvent, node: Node) => {
      setSelectedStage(Number(node.id))
    },
    [setSelectedStage]
  )

  return (
    <div
      style={{ height: 280, width: '100%' }}
      className="rounded-xl border border-[var(--color-border)] overflow-hidden"
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        colorMode="dark"
        style={{ background: '#0f1117' }}
      >
        <Background color="#2d3148" gap={20} size={1} />
        <Controls
          showInteractive={false}
          style={{ background: '#1a1d27', border: '1px solid #2d3148', borderRadius: 8 }}
        />
      </ReactFlow>
    </div>
  )
}
