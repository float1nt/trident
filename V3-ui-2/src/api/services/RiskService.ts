import { get, type ResponseData } from "@/utils/request";
import { normalizeApiList } from "@/utils/normalizeApiList";
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
    total: typeof value.total === "number" ? value.total : undefined,
    risk_type_total:
      typeof value.risk_type_total === "number"
        ? value.risk_type_total
        : undefined,
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

function buildEventTopologyParams(
  query: EventTopologyQuery,
): Record<string, string | number> {
  const params: Record<string, string | number> = {};
  const name = query.name?.trim();
  if (name) {
    params.name = name;
  }
  const attackTypes = query.attackTypes?.filter((code) => code.trim());
  if (attackTypes?.length) {
    params.attackTypes = attackTypes.join(",");
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
  if (query.limit != null) {
    params.limit = query.limit;
  }
  if (query.offset != null) {
    params.offset = query.offset;
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

export type AttackTypeOption = {
  code: string;
  name: string;
  desc: string;
  count?: number;
};

export type AttackTypesQuery = {
  scope?: "event" | "all";
  includeCount?: boolean;
};

export type EventTopologyQuery = {
  name?: string;
  attackTypes?: string[];
  triggerStart?: string;
  triggerEnd?: string;
  limit?: number;
  offset?: number;
};

export type IpEventsTopologyQuery = {
  limit?: number;
  offset?: number;
};

function buildIpEventsTopologyParams(
  query: IpEventsTopologyQuery,
): Record<string, string | number> {
  const params: Record<string, string | number> = {};
  if (query.limit != null) {
    params.limit = query.limit;
  }
  if (query.offset != null) {
    params.offset = query.offset;
  }
  return params;
}

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

export type TrafficLogsPageResponse = {
  items: RiskTrafficLogItem[];
  total: number;
  limit: number;
  offset: number;
};

function normalizeTrafficLogsPage(
  data: unknown,
  limit: number,
  offset: number,
): TrafficLogsPageResponse {
  const items = normalizeApiList<RiskTrafficLogItem>(data);
  if (data && typeof data === "object" && !Array.isArray(data)) {
    const obj = data as Record<string, unknown>;
    const total = typeof obj.total === "number" ? obj.total : items.length;
    return {
      items,
      total,
      limit: typeof obj.limit === "number" ? obj.limit : limit,
      offset: typeof obj.offset === "number" ? obj.offset : offset,
    };
  }
  return { items, total: items.length, limit, offset };
}

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
  learnerName?: string;
  triggerTime: string;
  description: string;
  features: string;
  riskScore?: number;
  riskBand?: string;
};

export type RiskDetail = RiskItem & {
  riskIpCount?: number;
  riskPortCount?: number;
};

export class RiskService {
  static async listRisks(query: RiskListQuery): Promise<RiskListResponse> {
    const res = await get<RiskListResponse | IpRiskListItem[]>("/risks", query);
    const data = res.data;
    if (!data) return { total: 0, risks: [] };
    if (Array.isArray(data)) {
      return { total: data.length, risks: data };
    }
    const risks = normalizeApiList<IpRiskListItem>(data);
    const total =
      typeof (data as RiskListResponse).total === "number"
        ? (data as RiskListResponse).total
        : risks.length;
    return { total, risks };
  }

  static async getAttackTypes(
    query: AttackTypesQuery = {},
  ): Promise<AttackTypeOption[]> {
    const params: Record<string, string | boolean> = {
      scope: query.scope ?? "event",
    };
    if (query.includeCount) {
      params.includeCount = true;
    }
    const res = await get<{ items?: AttackTypeOption[] } | AttackTypeOption[]>(
      "/risk/attack-types",
      params,
    );
    const data = res.data;
    if (Array.isArray(data)) {
      return data;
    }
    return normalizeApiList<AttackTypeOption>(data?.items);
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
    const res = await get<RiskIpListItem[] | { items?: RiskIpListItem[] }>(
      `/risks/${riskId}/ips`,
    );
    return normalizeApiList<RiskIpListItem>(res.data);
  }

  static async getRiskTrafficLogs(
    riskId: number,
    limit = 10,
    offset = 0,
  ): Promise<TrafficLogsPageResponse> {
    const res = await get<TrafficLogsPageResponse | RiskTrafficLogItem[]>(
      `/risks/${riskId}/traffic-logs`,
      { limit, offset },
    );
    return normalizeTrafficLogsPage(res.data, limit, offset);
  }

  static async getIpSummary(ip: string): Promise<IpSummary | null> {
    const res = await get<IpSummary>(`/risk/ips/${encodeURIComponent(ip)}/summary`);
    const data = res.data;
    if (!data?.ip) return null;
    return data;
  }

  static async getIpEventsTopology(
    ip: string,
    query: IpEventsTopologyQuery = {},
  ): Promise<LearnerNetworkTopologyJson> {
    const res = await get<LearnerNetworkTopologyJson>(
      `/risk/ips/${encodeURIComponent(ip)}/events/topology`,
      buildIpEventsTopologyParams(query),
      { timeout: 120_000 },
    );
    return unwrapEventTopology(res);
  }

  static async getIpEvents(ip: string): Promise<IpRiskEventItem[]> {
    const res = await get<IpRiskEventItem[]>(
      `/risk/ips/${encodeURIComponent(ip)}/events`,
    );
    return normalizeApiList<IpRiskEventItem>(res.data);
  }

  static async getIpTrafficLogs(
    ip: string,
    limit = 10,
    offset = 0,
  ): Promise<TrafficLogsPageResponse> {
    const res = await get<TrafficLogsPageResponse | RiskTrafficLogItem[]>(
      `/risk/ips/${encodeURIComponent(ip)}/traffic-logs`,
      { limit, offset },
    );
    return normalizeTrafficLogsPage(res.data, limit, offset);
  }
}
