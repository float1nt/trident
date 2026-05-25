import type { TopologyGraph } from '../components/NetworkTopologyPanel'

export type LearnerTopologyView = {
  learner: string
  attack_ratio: number
  dominant_label?: string
  dominant_ratio?: number
  is_benign: boolean | null
  host: TopologyGraph
  endpoint: TopologyGraph
}

export type LearnerNetworkTopologyJson = {
  version: number
  learners: string[]
  default_learner: string
  views: Record<string, LearnerTopologyView>
}

export type LearnerTopologyOption = {
  name: string
  attackRatio: number
  dominantLabel: string
  flowCount?: number
}

export type StrengthBand = 'VERY_LOW' | 'LOW' | 'MID' | 'HIGH' | 'VERY_HIGH'

export type LearnerMetricAuditItem = {
  group: string
  metric_key: string
  metric_name: string
  raw_value: number
  /** Feature strength 0–100, not risk */
  score_0_100: number
  trait_axis?: string
  trait_axis_label?: string
  strength_band?: StrengthBand
  strength_label?: string
  semantic_tag?: string
  semantic_text: string
  /** @deprecated Use strength_band / semantic_tag; legacy exports only */
  semantic_level?: string
}

export type LearnerMetricHint = {
  hint_key: string
  hint_text: string
}

export type LearnerMetricAuditView = {
  learner_name: string
  flow_count: number
  attack_ratio?: number | null
  dominant_label?: string | null
  dominant_ratio?: number | null
  metrics: LearnerMetricAuditItem[]
  qualitative_hints?: LearnerMetricHint[]
}

export type LearnerSkippedEntry = {
  learner_name: string
  reason: string
  flow_count_joined?: number
  label_distribution_samples?: number
}

export type LearnerTopologyMetricAuditJson = {
  version: number
  learners: LearnerMetricAuditView[]
  learners_skipped?: LearnerSkippedEntry[]
  export_filters?: {
    min_samples?: number
    max_learners?: number
    assignment_phase?: string
  }
}
