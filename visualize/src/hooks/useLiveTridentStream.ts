import { useCallback, useEffect, useRef, useState } from 'react'
import {
  createLiveEventSource,
  fetchLiveStreamConfig,
  initialLiveTridentState,
  isMetricAuditPayload,
  type LearnerLabelDistributionRow,
  type LiveStreamEnvelope,
  type LiveTridentState,
  type WindowClosedPayload,
} from '../lib/liveApi'
import type { LearnerTopologyMetricAuditJson } from '../types/learnerTopology'

type UseLiveTridentStreamOptions = {
  enabled?: boolean
  maxWindows?: number
}

export function useLiveTridentStream(options: UseLiveTridentStreamOptions = {}) {
  const { enabled = true, maxWindows = 500 } = options
  const [state, setState] = useState<LiveTridentState>(initialLiveTridentState)
  const [configEnabled, setConfigEnabled] = useState<boolean | null>(null)
  const esRef = useRef<EventSource | null>(null)

  const applyEnvelope = useCallback(
    (eventType: string, envelope: LiveStreamEnvelope) => {
      setState((prev) => {
        const next: LiveTridentState = {
          ...prev,
          eventCount: prev.eventCount + 1,
          lastEventType: eventType,
          lastEventAt: envelope.ts || new Date().toISOString(),
          runId: envelope.run_id || prev.runId,
        }

        const payload = envelope.payload
        if (eventType === 'connected') {
          next.connected = true
          next.connecting = false
          next.error = null
          return next
        }
        if (eventType === 'run_started') {
          next.runStartedAt = envelope.ts || next.runStartedAt
          next.runFinished = false
          next.windows = []
          next.metricAudit = null
          next.labelDistributionRows = []
          return next
        }
        if (eventType === 'window_closed' && payload && typeof payload === 'object') {
          const row = payload as WindowClosedPayload
          next.windows = [...prev.windows, row].slice(-maxWindows)
          return next
        }
        if (eventType === 'learner_metric_audit' && isMetricAuditPayload(payload)) {
          next.metricAudit = payload as LearnerTopologyMetricAuditJson
          return next
        }
        if (eventType === 'learner_label_distribution' && payload && typeof payload === 'object') {
          const rows = (payload as { rows?: LearnerLabelDistributionRow[] }).rows
          if (Array.isArray(rows)) {
            next.labelDistributionRows = rows
          }
          return next
        }
        if (eventType === 'run_finished') {
          next.runFinished = true
          return next
        }
        if (eventType === 'error') {
          const message =
            payload && typeof payload === 'object' && 'message' in payload
              ? String((payload as { message?: string }).message || 'Live stream error')
              : 'Live stream error'
          next.error = message
          next.connected = false
          return next
        }
        return next
      })
    },
    [maxWindows],
  )

  const disconnect = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
    setState((prev) => ({ ...prev, connected: false, connecting: false }))
  }, [])

  const connect = useCallback(() => {
    disconnect()
    setState((prev) => ({
      ...initialLiveTridentState,
      connecting: true,
      runId: prev.runId,
    }))

    const es = createLiveEventSource('0-0')
    esRef.current = es

    const bind = (eventType: string) => {
      es.addEventListener(eventType, (ev) => {
        try {
          const envelope = JSON.parse((ev as MessageEvent).data) as LiveStreamEnvelope
          applyEnvelope(eventType, envelope)
        } catch (err) {
          setState((prev) => ({
            ...prev,
            error: err instanceof Error ? err.message : String(err),
            connected: false,
            connecting: false,
          }))
        }
      })
    }

    ;[
      'connected',
      'run_started',
      'window_closed',
      'learner_metric_audit',
      'learner_label_distribution',
      'run_finished',
      'error',
    ].forEach(bind)

    es.onerror = () => {
      setState((prev) => ({
        ...prev,
        connected: false,
        connecting: false,
        error: prev.error || 'SSE 连接中断，请检查 Trident 是否正在写入 outputs/runs/ 产物。',
      }))
    }
  }, [applyEnvelope, disconnect])

  useEffect(() => {
    if (!enabled) {
      disconnect()
      return
    }
    fetchLiveStreamConfig()
      .then((cfg) => {
        setConfigEnabled(cfg.enabled)
        if (!cfg.enabled) {
          setState((prev) => ({
            ...prev,
            connecting: false,
            error: 'Live artifact watch 未启用。请在 configs/config.yaml 设置 visualization.live_flush_enabled，或 export TRIDENT_LIVE_ARTIFACTS_ENABLED=1。',
          }))
          return
        }
        connect()
      })
      .catch((err) => {
        setState((prev) => ({
          ...prev,
          connecting: false,
          error: err instanceof Error ? err.message : String(err),
        }))
      })
    return () => disconnect()
  }, [enabled, connect, disconnect])

  return {
    ...state,
    configEnabled,
    reconnect: connect,
    disconnect,
  }
}
