import { get } from "@/utils/request";
import type { IpRiskListItem, RiskItem } from "@/api/types";
import type { DatasetNetworkTopologyJson } from "@/components/NetworkTopologyPanel";
import type { LearnerNetworkTopologyJson } from "@/types/learnerTopology";

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
  time: string;
  ip: string;
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
      query,
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

  static async getRiskById(riskId: number): Promise<RiskDetail | null> {
    const res = await get<RiskDetail>(`/risks/${riskId}`);
    return res.data ?? null;
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
    limit = 100,
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
    return res.data ?? null;
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
    limit = 100,
    offset = 0,
  ): Promise<RiskTrafficLogItem[]> {
    const res = await get<RiskTrafficLogItem[]>(
      `/risk/ips/${encodeURIComponent(ip)}/traffic-logs`,
      { limit, offset },
    );
    return res.data ?? [];
  }
}
