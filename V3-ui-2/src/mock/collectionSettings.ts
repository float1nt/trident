import type {
  CollectionSettings,
  ProtocolOption,
} from "@/types/collectionSettings";

/** 协议选项（与 backend-api-spec 一致，待 streamtrident trident-api 实现后改走接口） */
export const MOCK_PROTOCOL_OPTIONS: ProtocolOption[] = [
  { value: "TCP", label: "TCP" },
  { value: "UDP", label: "UDP" },
  { value: "HTTP", label: "HTTP" },
  { value: "HTTPS", label: "HTTPS" },
  { value: "DNS", label: "DNS" },
  { value: "SSH", label: "SSH" },
  { value: "SMB", label: "SMB" },
  { value: "RDP", label: "RDP" },
  { value: "ICMP", label: "ICMP" },
  { value: "TLS", label: "TLS" },
  { value: "FTP", label: "FTP" },
  { value: "OTHER", label: "其他" },
];

const DEFAULT_SETTINGS: CollectionSettings = {
  maxTrafficLimitGbps: 10,
  sourceIpRanges: [{ startIp: "10.0.0.0", endIp: "10.255.255.255" }],
  destIpRanges: [{ startIp: "0.0.0.0", endIp: "255.255.255.255" }],
  protocols: ["TCP", "UDP", "HTTPS", "HTTP", "DNS"],
};

let settingsStore: CollectionSettings = structuredClone(DEFAULT_SETTINGS);

export function mockGetCollectionSettings(): Promise<CollectionSettings> {
  return Promise.resolve(structuredClone(settingsStore));
}

export function mockSaveCollectionSettings(
  data: CollectionSettings,
): Promise<CollectionSettings> {
  settingsStore = structuredClone(data);
  return Promise.resolve(structuredClone(settingsStore));
}

export function mockGetCollectionProtocols(): Promise<ProtocolOption[]> {
  return Promise.resolve([...MOCK_PROTOCOL_OPTIONS]);
}
