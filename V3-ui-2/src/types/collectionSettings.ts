import type { IpRangeItem } from "@/components/IpRangeFormList";

export interface CollectionSettings {
  maxTrafficLimitGbps: number;
  sourceIpRanges: IpRangeItem[];
  destIpRanges: IpRangeItem[];
  protocols: string[];
}

export interface ProtocolOption {
  value: string;
  label: string;
}

export interface CollectionAgentApplyResult {
  name: string;
  url: string;
  ok: boolean;
  response?: Record<string, unknown>;
  error?: string;
}

export interface CollectionApplyResult {
  applied: boolean;
  agents: CollectionAgentApplyResult[];
  message?: string;
}

export interface CollectionSettingsState {
  settings: CollectionSettings;
  revision: number;
  lastApply?: CollectionApplyResult | null;
}

export interface CollectionSettingsSaveResult {
  settings: CollectionSettings;
  revision: number;
  apply: CollectionApplyResult;
}

export interface CollectionAgentRuntimeStatus {
  iface?: string;
  sampledAt?: string;
  filter?: {
    version?: number | null;
    policyHash?: string | null;
  };
  suricata?: {
    running?: boolean;
    status?: string;
  };
  redis?: {
    type?: string;
    length?: number | null;
    key?: string;
    error?: string;
  };
}

export interface CollectionAgentStatusItem {
  name: string;
  url: string;
  reachable: boolean;
  effective: boolean;
  desiredRevision?: number | null;
  effectiveRevision?: number | null;
  status?: CollectionAgentRuntimeStatus | null;
  sampledAt?: string | null;
  error?: string | null;
}

export interface CollectionAgentStatusResponse {
  desiredRevision: number;
  agents: CollectionAgentStatusItem[];
}
