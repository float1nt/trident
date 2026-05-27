import type {
  LearnerNetworkTopologyJson,
  LearnerTopologyView,
} from "@/types/learnerTopology";
import {
  getMockIpRiskEvents,
  getMockRiskNetworkTopology,
  type IpRiskEventItem,
} from "@/mock/riskTasks";

const LEARNER_META: Array<{
  name: string;
  riskId: number;
  riskName: string;
  riskDescription: string;
  triggerTime: string;
  attackRatio: number;
  dominantLabel: string;
  dominantRatio: number;
}> = [
  {
    name: "learner_lstm_https",
    riskId: 1,
    riskName: "异常外联至境外 C2",
    riskDescription:
      "内网主机持续向境外可疑 IP 发起 HTTPS 长连接，流量特征与已知 C2 通信一致。",
    triggerTime: "2026-05-25 09:12:33",
    attackRatio: 0.382,
    dominantLabel: "HTTPS",
    dominantRatio: 0.54,
  },
  {
    name: "learner_gmm_ssh",
    riskId: 2,
    riskName: "暴力破解 SSH 服务",
    riskDescription:
      "同一源地址在 10 分钟内对 SSH 端口发起超 500 次认证失败尝试。",
    triggerTime: "2026-05-24 22:41:07",
    attackRatio: 0.291,
    dominantLabel: "SSH",
    dominantRatio: 0.48,
  },
  {
    name: "learner_rf_dns",
    riskId: 3,
    riskName: "敏感文件批量下载",
    riskDescription:
      "办公网账号短时间内从文档库拉取大量含「客户合同」标签的文件。",
    triggerTime: "2026-05-24 16:28:19",
    attackRatio: 0.224,
    dominantLabel: "DNS",
    dominantRatio: 0.41,
  },
  {
    name: "learner_xgb_smb",
    riskId: 4,
    riskName: "横向移动扫描行为",
    riskDescription:
      "主机对网段内多台服务器 445/135/3389 端口进行顺序探测。",
    triggerTime: "2026-05-23 11:05:44",
    attackRatio: 0.176,
    dominantLabel: "SMB",
    dominantRatio: 0.37,
  },
  {
    name: "learner_kmeans_http",
    riskId: 5,
    riskName: "Web 应用 SQL 注入尝试",
    riskDescription: "对外业务站点收到携带 union select 等特征的恶意请求。",
    triggerTime: "2026-05-23 08:33:51",
    attackRatio: 0.118,
    dominantLabel: "HTTP",
    dominantRatio: 0.33,
  },
  {
    name: "learner_iforest_tls",
    riskId: 6,
    riskName: "挖矿进程驻留",
    riskDescription:
      "Linux 主机 CPU 持续高位，发现伪装系统服务的 xmrig 相关进程。",
    triggerTime: "2026-05-22 19:17:02",
    attackRatio: 0.063,
    dominantLabel: "TLS",
    dominantRatio: 0.29,
  },
];

function buildLearnerView(meta: (typeof LEARNER_META)[number]): LearnerTopologyView | null {
  const topology = getMockRiskNetworkTopology(meta.riskId);
  const combined = topology?.views.__combined__;
  if (!combined) return null;

  return {
    learner: meta.name,
    risk_id: meta.riskId,
    risk_name: meta.riskName,
    risk_description: meta.riskDescription,
    trigger_time: meta.triggerTime,
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
      item.riskName.toLowerCase().includes(keyword) ||
      item.riskDescription.toLowerCase().includes(keyword)
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

const IP_RISK_DOMINANT_LABELS = [
  "HTTPS",
  "SSH",
  "DNS",
  "SMB",
  "HTTP",
  "TLS",
] as const;

function buildIpRiskEventView(
  event: IpRiskEventItem,
  index: number,
  viewKey: string,
): LearnerTopologyView | null {
  const topologyRiskId = event.id < 10000 ? event.id : (event.id % 12) + 1;
  const topology = getMockRiskNetworkTopology(topologyRiskId);
  const combined = topology?.views.__combined__;
  if (!combined) return null;

  return {
    learner: viewKey,
    risk_id: event.id < 10000 ? event.id : topologyRiskId,
    risk_name: event.name,
    risk_description: event.description,
    trigger_time: event.triggerTime,
    attack_ratio: Math.max(0.05, 0.38 - index * 0.055),
    dominant_label: IP_RISK_DOMINANT_LABELS[index % IP_RISK_DOMINANT_LABELS.length],
    dominant_ratio: 0.29 + (index % 3) * 0.08,
    is_benign: null,
    host: combined.host,
    endpoint: combined.endpoint,
  };
}

/** IP 详情 — 与 IP 关联的风险事件拓扑 mock */
export function getMockIpRiskEventTopology(
  ip: string,
): LearnerNetworkTopologyJson {
  const normalized = ip.trim();
  const events = normalized ? getMockIpRiskEvents(normalized).slice(0, 6) : [];
  const views: Record<string, LearnerTopologyView> = {};
  const learners: string[] = [];

  events.forEach((event, index) => {
    const viewKey = `ip_risk_${event.id}`;
    const view = buildIpRiskEventView(event, index, viewKey);
    if (!view) return;
    views[viewKey] = view;
    learners.push(viewKey);
  });

  return {
    version: 1,
    learners,
    default_learner: learners[0] ?? "",
    views,
  };
}
