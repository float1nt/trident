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
