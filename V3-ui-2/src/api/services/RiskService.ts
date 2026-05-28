import { get, type ResponseData } from "@/utils/request";
import type { IpRiskListItem, RiskItem } from "@/api/types";
import type { DatasetNetworkTopologyJson } from "@/components/NetworkTopologyPanel";
import type { LearnerNetworkTopologyJson } from "@/types/learnerTopology";

const EMPTY_EVENT_TOPOLOGY: LearnerNetworkTopologyJson = {
  version: 1,
  learners: [],
  default_learner: "",
  views: {},
};

function isEventTopologyPayload(value: unknown): value is LearnerNetworkTopologyJson {
  return (
    !!value &&
    typeof value === "object" &&
    typeof (value as LearnerNetworkTopologyJson).views === "object" &&
    (Array.isArray((value as LearnerNetworkTopologyJson).learners) ||
      !!(value as LearnerNetworkTopologyJson).views)
  );
}

function normalizeEventTopology(value: LearnerNetworkTopologyJson): LearnerNetworkTopologyJson {
  const views =
    value.views && typeof value.views === "object"
      ? (value.views as LearnerNetworkTopologyJson["views"])
      : {};
  const learners =
    Array.isArray(value.learners) && value.learners.length > 0
      ? value.learners
      : Object.keys(views);
  return {
    version: value.version ?? 1,
    learners,
    default_learner:
      value.default_learner && learners.includes(value.default_learner)
        ? value.default_learner
        : learners[0] ?? "",
    views,
  };
}

function findEventTopologyInObject(root: unknown): LearnerNetworkTopologyJson | null {
  const queue: unknown[] = [root];
  const seen = new Set<unknown>();

  while (queue.length > 0) {
    const cur = queue.shift();
    if (!cur || typeof cur !== "object" || seen.has(cur)) continue;
    seen.add(cur);

    if (isEventTopologyPayload(cur)) {
      return normalizeEventTopology(cur as LearnerNetworkTopologyJson);
    }

    for (const value of Object.values(cur as Record<string, unknown>)) {
      if (value && typeof value === "object") queue.push(value);
    }
  }
  return null;
}

function buildEventTopologyParams(query: EventTopologyQuery): Record<string, string> {
  const params: Record<string, string> = {};
  const name = query.name?.trim();
  if (name) {
    params.name = name;
  }
  const start = query.triggerStart?.trim();
  const end = query.triggerEnd?.trim();
  if (
    start &&
    end &&
    start.toLowerCase() !== "undefined" &&
    end.toLowerCase() !== "undefined"
  ) {
    params.triggerStart = start;
    params.triggerEnd = end;
  }
  return params;
}

function unwrapEventTopology(
  res: ResponseData<LearnerNetworkTopologyJson> | LearnerNetworkTopologyJson,
): LearnerNetworkTopologyJson {
  const fromTree = findEventTopologyInObject(res);
  if (fromTree) return fromTree;
  return EMPTY_EVENT_TOPOLOGY;
}

export type RiskListQuery = {
  limit: number;
  offset: number;
  name?: string;
  subjectIp?: string;
};

export type RiskListResponse = {
  total: number;
  risks: IpRiskListItem[];
};

export type EventTopologyQuery = {
  name?: string;
  triggerStart?: string;
  triggerEnd?: string;
};

export type RiskIpListItem = {
  ip: string;
  triggerCount: number;
};

export type RiskTrafficLogItem = {
  id: string;
  srcIp: string;
  srcPort: number;
  dstIp: string;
  dstPort: number;
  accessTime: string;
  traffic: number;
  protocol: string;
};

export type IpSummary = {
  ip: string;
  description: string;
  features: string;
  riskEventCount: number;
  latestTriggerTime: string;
  isInternal: boolean;
};

export type IpRiskEventItem = {
  id: number;
  name: string;
  triggerTime: string;
  description: string;
  features: string;
};

export type RiskDetail = RiskItem & {
  riskIpCount?: number;
  riskPortCount?: number;
};

export class RiskService {
  static async listRisks(query: RiskListQuery): Promise<RiskListResponse> {
    const res = await get<RiskListResponse>("/risks", query);
    return res.data ?? { total: 0, risks: [] };
  }

  static async getEventTopology(
    query: EventTopologyQuery = {},
  ): Promise<LearnerNetworkTopologyJson> {
    const res = await get<LearnerNetworkTopologyJson>(
      "/risk/events/topology",
      buildEventTopologyParams(query),
      { timeout: 120_000 },
    );
    return unwrapEventTopology(res);
  }

  static async getRiskById(riskId: number): Promise<RiskDetail | null> {
    const res = await get<RiskDetail>(`/risks/${riskId}`);
    const data = res.data;
    if (!data?.id) return null;
    return data;
  }

  static async getRiskNetworkTopology(
    riskId: number,
  ): Promise<DatasetNetworkTopologyJson | null> {
    const res = await get<DatasetNetworkTopologyJson>(
      `/risks/${riskId}/network-topology`,
    );
    return res.data ?? null;
  }

  static async getRiskIps(riskId: number): Promise<RiskIpListItem[]> {
    const res = await get<RiskIpListItem[]>(`/risks/${riskId}/ips`);
    return res.data ?? [];
  }

  static async getRiskTrafficLogs(
    riskId: number,
    limit = 10,
    offset = 0,
  ): Promise<RiskTrafficLogItem[]> {
    const res = await get<RiskTrafficLogItem[]>(
      `/risks/${riskId}/traffic-logs`,
      { limit, offset },
    );
    return res.data ?? [];
  }

  static async getIpSummary(ip: string): Promise<IpSummary | null> {
    const res = await get<IpSummary>(`/risk/ips/${encodeURIComponent(ip)}/summary`);
    const data = res.data;
    if (!data?.ip) return null;
    return data;
  }

  static async getIpEventsTopology(
    ip: string,
  ): Promise<LearnerNetworkTopologyJson> {
    const res = await get<LearnerNetworkTopologyJson>(
      `/risk/ips/${encodeURIComponent(ip)}/events/topology`,
    );
    return (
      res.data ?? {
        version: 1,
        learners: [],
        default_learner: "",
        views: {},
      }
    );
  }

  static async getIpEvents(ip: string): Promise<IpRiskEventItem[]> {
    const res = await get<IpRiskEventItem[]>(
      `/risk/ips/${encodeURIComponent(ip)}/events`,
    );
    return res.data ?? [];
  }

  static async getIpTrafficLogs(
    ip: string,
    limit = 10,
    offset = 0,
  ): Promise<RiskTrafficLogItem[]> {
    const res = await get<RiskTrafficLogItem[]>(
      `/risk/ips/${encodeURIComponent(ip)}/traffic-logs`,
      { limit, offset },
    );
    return res.data ?? [];
  }
}
