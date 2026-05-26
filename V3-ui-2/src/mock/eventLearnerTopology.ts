import type {
  LearnerNetworkTopologyJson,
  LearnerTopologyView,
} from "@/types/learnerTopology";
import { getMockRiskNetworkTopology, getMockRiskById } from "@/mock/riskTasks";

const LEARNER_META: Array<{
  name: string;
  riskId: number;
  attackRatio: number;
  dominantLabel: string;
  dominantRatio: number;
}> = [
  {
    name: "learner_lstm_https",
    riskId: 1,
    attackRatio: 0.382,
    dominantLabel: "HTTPS",
    dominantRatio: 0.54,
  },
  {
    name: "learner_gmm_ssh",
    riskId: 2,
    attackRatio: 0.291,
    dominantLabel: "SSH",
    dominantRatio: 0.48,
  },
  {
    name: "learner_rf_dns",
    riskId: 3,
    attackRatio: 0.224,
    dominantLabel: "DNS",
    dominantRatio: 0.41,
  },
  {
    name: "learner_xgb_smb",
    riskId: 4,
    attackRatio: 0.176,
    dominantLabel: "SMB",
    dominantRatio: 0.37,
  },
  {
    name: "learner_kmeans_http",
    riskId: 5,
    attackRatio: 0.118,
    dominantLabel: "HTTP",
    dominantRatio: 0.33,
  },
  {
    name: "learner_iforest_tls",
    riskId: 6,
    attackRatio: 0.063,
    dominantLabel: "TLS",
    dominantRatio: 0.29,
  },
];

function buildLearnerView(meta: (typeof LEARNER_META)[number]): LearnerTopologyView | null {
  const topology = getMockRiskNetworkTopology(meta.riskId);
  const combined = topology?.views.__combined__;
  if (!combined) return null;

  const risk = getMockRiskById(meta.riskId);

  return {
    learner: meta.name,
    risk_id: meta.riskId,
    risk_name: risk?.name,
    attack_ratio: meta.attackRatio,
    dominant_label: meta.dominantLabel,
    dominant_ratio: meta.dominantRatio,
    is_benign: null,
    host: combined.host,
    endpoint: combined.endpoint,
  };
}

export type EventLearnerTopologyFilters = {
  name?: string;
};

/** 事件视角 — 学习器内部网络拓扑 mock */
export function getMockEventLearnerTopology(
  filters: EventLearnerTopologyFilters = {},
): LearnerNetworkTopologyJson {
  const keyword = (filters.name ?? "").trim().toLowerCase();
  const matchedMeta = LEARNER_META.filter((item) => {
    if (!keyword) return true;
    return (
      item.name.toLowerCase().includes(keyword) ||
      item.dominantLabel.toLowerCase().includes(keyword) ||
      (getMockRiskById(item.riskId)?.name.toLowerCase().includes(keyword) ?? false)
    );
  });

  const views: Record<string, LearnerTopologyView> = {};
  matchedMeta.forEach((meta) => {
    const view = buildLearnerView(meta);
    if (view) views[meta.name] = view;
  });

  const learners = matchedMeta
    .map((item) => item.name)
    .filter((name) => views[name])
    .sort(
      (a, b) =>
        (views[b]?.attack_ratio ?? 0) - (views[a]?.attack_ratio ?? 0) ||
        a.localeCompare(b),
    );

  return {
    version: 1,
    learners,
    default_learner: learners[0] ?? "",
    views,
  };
}
