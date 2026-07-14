import { useEffect, useRef } from 'react'
import { usePipelineStore } from './usePipelineStore'
import type { StageEvent } from '../types/events'

/**
 * Open one WebSocket per jobId. Sockets for removed jobs are closed automatically.
 * Each event is tagged with its job_id before being dispatched to the store, so
 * the store can route to the right run.
 */
export function usePipelineSockets(jobIds: string[]) {
  const handleEvent = usePipelineStore((s) => s.handleEvent)
  const socketsRef = useRef<Map<string, WebSocket>>(new Map())
  const idsKey = jobIds.join(',')

  useEffect(() => {
    const sockets = socketsRef.current
    const desired = new Set(jobIds)

    // Close sockets for jobs no longer in the list
    for (const [id, ws] of sockets.entries()) {
      if (!desired.has(id)) {
        try { ws.close() } catch { /* ignore */ }
        sockets.delete(id)
      }
    }

    // Open sockets for new jobs
    for (const id of jobIds) {
      if (sockets.has(id)) continue
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${window.location.host}/ws/${id}`)

      ws.onmessage = (e) => {
        try {
          const event: StageEvent = JSON.parse(e.data)
          if (event.stage_id) handleEvent(event)
        } catch {
          // ignore non-JSON frames (e.g. pong)
        }
      }

      sockets.set(id, ws)
    }

    // Keepalive ping every 25s for all open sockets
    const ping = setInterval(() => {
      for (const ws of sockets.values()) {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }
    }, 25_000)

    return () => {
      clearInterval(ping)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey, handleEvent])

  useEffect(() => {
    // Cleanup all sockets on unmount
    return () => {
      for (const ws of socketsRef.current.values()) {
        try { ws.close() } catch { /* ignore */ }
      }
      socketsRef.current.clear()
    }
  }, [])

  return socketsRef
}

/** Backward-compat single-socket version — wraps usePipelineSockets. */
export function usePipelineSocket(jobId: string | null) {
  const ids = jobId ? [jobId] : []
  return usePipelineSockets(ids)
}
