import type {
  CollectionSettings,
  ProtocolOption,
} from "@/api/services/SettingService";

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

export const MOCK_COLLECTION_SETTINGS: CollectionSettings = {
  maxTrafficLimitGbps: 10,
  sourceIpRanges: [
    { startIp: "10.0.0.0", endIp: "10.255.255.255" },
    { startIp: "172.16.0.0", endIp: "172.31.255.255" },
  ],
  destIpRanges: [{ startIp: "0.0.0.0", endIp: "255.255.255.255" }],
  protocols: ["TCP", "UDP", "HTTPS", "HTTP", "DNS"],
};
