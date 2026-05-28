import type { TopologyGraph } from "@/components/NetworkTopologyPanel";

export type LearnerTopologyView = {
  learner: string;
  risk_id: number;
  risk_name?: string;
  risk_description?: string;
  trigger_time?: string;
  attack_ratio: number;
  dominant_label?: string;
  dominant_ratio?: number;
  is_benign: boolean | null;
  host: TopologyGraph;
  endpoint: TopologyGraph;
};

export type LearnerNetworkTopologyJson = {
  version: number;
  total?: number;
  risk_event_total?: number;
  learners: string[];
  default_learner: string;
  views: Record<string, LearnerTopologyView>;
};

export type LearnerTopologyOption = {
  name: string;
  riskId: number;
  riskName: string;
  riskDescription: string;
  triggerTime: string;
  attackRatio: number;
  dominantLabel: string;
  flowCount?: number;
};
