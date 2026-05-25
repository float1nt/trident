import type { RiskItem } from "@/api/types";
import type {
  DatasetNetworkTopologyJson,
  TopologyGraph,
} from "@/modules/overview/components/NetworkTopologyPanel";

const mockRisks: RiskItem[] = [
  {
    id: 1,
    subjectIp: "10.12.45.88",
    name: "异常外联至境外 C2",
    triggerTime: "2026-05-25 09:12:33",
    description: "内网主机持续向境外可疑 IP 发起 HTTPS 长连接，流量特征与已知 C2 通信一致。",
    features: "高频外联、TLS 指纹异常、非业务时段活跃",
  },
  {
    id: 2,
    subjectIp: "172.16.8.23",
    name: "暴力破解 SSH 服务",
    triggerTime: "2026-05-24 22:41:07",
    description: "同一源地址在 10 分钟内对 SSH 端口发起超 500 次认证失败尝试。",
    features: "认证失败激增、固定目标端口、字典口令特征",
  },
  {
    id: 3,
    subjectIp: "192.168.3.156",
    name: "敏感文件批量下载",
    triggerTime: "2026-05-24 16:28:19",
    description: "办公网账号短时间内从文档库拉取大量含「客户合同」标签的文件。",
    features: "批量下载、敏感标签命中、偏离基线行为",
  },
  {
    id: 4,
    subjectIp: "10.8.19.4",
    name: "横向移动扫描行为",
    triggerTime: "2026-05-23 11:05:44",
    description: "主机对网段内多台服务器 445/135/3389 端口进行顺序探测。",
    features: "端口扫描、内网横向、短时间多目标",
  },
  {
    id: 5,
    subjectIp: "203.0.113.17",
    name: "Web 应用 SQL 注入尝试",
    triggerTime: "2026-05-23 08:33:51",
    description: "对外业务站点收到携带 union select 等特征的恶意请求。",
    features: "注入关键字、WAF 告警、同一 UA 重复出现",
  },
  {
    id: 6,
    subjectIp: "10.20.6.91",
    name: "挖矿进程驻留",
    triggerTime: "2026-05-22 19:17:02",
    description: "Linux 主机 CPU 持续高位，发现伪装系统服务的 xmrig 相关进程。",
    features: "CPU 异常、矿池域名解析、可疑进程名",
  },
  {
    id: 7,
    subjectIp: "192.168.12.77",
    name: "钓鱼邮件点击",
    triggerTime: "2026-05-22 14:02:18",
    description: "用户点击仿冒财务通知邮件中的短链，浏览器访问了恶意落地页。",
    features: "邮件网关告警、短链跳转、新注册域名",
  },
  {
    id: 8,
    subjectIp: "10.5.33.102",
    name: "特权账号异常登录",
    triggerTime: "2026-05-21 23:58:40",
    description: "域管账号在非工作时间从陌生地理位置成功登录 VPN。",
    features: "异地登录、非工作时段、高权限账号",
  },
  {
    id: 9,
    subjectIp: "172.31.0.44",
    name: "DNS 隧道数据传输",
    triggerTime: "2026-05-21 10:44:29",
    description: "客户端对同一域名发起异常高频 TXT 查询，载荷长度显著高于正常业务。",
    features: "TXT 记录异常、子域随机化、高熵请求",
  },
  {
    id: 10,
    subjectIp: "10.15.2.8",
    name: "勒索软件文件加密",
    triggerTime: "2026-05-20 17:33:12",
    description: "文件服务器出现大量扩展名被批量修改，并生成 README_FOR_DECRYPT 说明文件。",
    features: "批量改扩展名、赎金说明文件、SMB 写入异常",
  },
  {
    id: 11,
    subjectIp: "192.168.50.19",
    name: "API 密钥泄露利用",
    triggerTime: "2026-05-20 09:21:55",
    description: "云平台访问日志显示已撤销密钥仍被用于对象存储枚举与下载。",
    features: "密钥复用、云 API 异常调用、大量 List 操作",
  },
  {
    id: 12,
    subjectIp: "10.9.88.201",
    name: "供应链依赖投毒",
    triggerTime: "2026-05-19 13:09:37",
    description: "构建流水线拉取了与官方校验和不一致的第三方 npm 包版本。",
    features: "校验和不匹配、构建环境告警、非官方源",
  },
];

export interface MockRiskListParams {
  limit: number;
  offset: number;
  name?: string;
  subjectIp?: string;
  description?: string;
  triggerTime?: string;
}

export interface MockRiskListResult {
  total: number;
  risks: RiskItem[];
}

/** 模拟分页查询 */
export function fetchMockRiskList(
  params: MockRiskListParams
): Promise<MockRiskListResult> {
  return new Promise((resolve) => {
    setTimeout(() => {
      const name = (params.name ?? "").trim().toLowerCase();
      const subjectIp = (params.subjectIp ?? "").trim().toLowerCase();
      const description = (params.description ?? "").trim().toLowerCase();
      const triggerTime = (params.triggerTime ?? "").trim().toLowerCase();

      let filtered = mockRisks;
      if (name) {
        filtered = filtered.filter((r) =>
          r.name.toLowerCase().includes(name)
        );
      }
      if (subjectIp) {
        filtered = filtered.filter((r) =>
          r.subjectIp.toLowerCase().includes(subjectIp)
        );
      }
      if (description) {
        filtered = filtered.filter((r) =>
          r.description.toLowerCase().includes(description)
        );
      }
      if (triggerTime) {
        filtered = filtered.filter((r) =>
          r.triggerTime.toLowerCase().includes(triggerTime)
        );
      }
      const total = filtered.length;
      const slice = filtered.slice(
        params.offset,
        params.offset + params.limit
      );
      resolve({ total, risks: slice });
    }, 200);
  });
}

export function getMockRiskById(id: number): RiskItem | undefined {
  return mockRisks.find((r) => r.id === id);
}

export interface ProtocolDistributionItem {
  name: string;
  value: number;
}

const PROTOCOL_NAMES = [
  "TCP",
  "UDP",
  "HTTPS",
  "HTTP",
  "DNS",
  "SSH",
  "SMB",
  "RDP",
  "ICMP",
  "TLS",
  "FTP",
  "其他",
] as const;

/** 按风险 ID 生成更大体量的协议分布 mock（会话数级） */
function buildProtocolDistribution(riskId: number): ProtocolDistributionItem[] {
  const baseWeights = [
    4200, 2800, 5600, 3100, 1900, 1200, 980, 760, 640, 2200, 420, 380,
  ];
  const shift = riskId % PROTOCOL_NAMES.length;

  return PROTOCOL_NAMES.map((name, index) => {
    const weightIndex = (index + shift) % baseWeights.length;
    const multiplier = 1 + (riskId % 4) * 0.35 + (index % 3) * 0.12;
    return {
      name,
      value: Math.round(baseWeights[weightIndex] * multiplier),
    };
  });
}

export function getMockProtocolDistribution(
  riskId: number
): ProtocolDistributionItem[] {
  return buildProtocolDistribution(riskId);
}

function isInternalIp(ip: string): boolean {
  return (
    ip.startsWith("10.") ||
    ip.startsWith("192.168.") ||
    ip.startsWith("172.16.") ||
    ip.startsWith("172.17.") ||
    ip.startsWith("172.18.") ||
    ip.startsWith("172.19.") ||
    ip.startsWith("172.2") ||
    ip.startsWith("172.30.") ||
    ip.startsWith("172.31.")
  );
}

function pseudoRandom(seed: number, salt: number): number {
  const x = Math.sin(seed * 9301 + salt * 49297) * 10000;
  return x - Math.floor(x);
}

const INTERNAL_SUBNETS = [
  "10.12.45",
  "10.20.6",
  "192.168.3",
  "172.16.8",
  "10.8.19",
  "10.5.33",
  "192.168.12",
  "10.15.2",
] as const;

const EXTERNAL_IP_PREFIXES = [
  "203.0.113",
  "198.51.100",
  "192.0.2",
  "185.220.101",
  "45.33.32",
  "91.219.236",
] as const;

const COMMON_PORTS = [22, 53, 80, 135, 443, 445, 3389, 8080, 8443, 9200] as const;

function buildMockHostGraph(subjectIp: string, seed: number): TopologyGraph {
  const internal = isInternalIp(subjectIp);
  const nodeMap = new Map<
    string,
  {
    id: string;
    ip: string;
    port: null;
    flow_count: number;
    is_internal: boolean;
  }
  >();

  nodeMap.set(subjectIp, {
    id: subjectIp,
    ip: subjectIp,
    port: null,
    flow_count: 8600 + seed * 420,
    is_internal: internal,
  });

  for (let i = 0; i < 36; i += 1) {
    const subnet = INTERNAL_SUBNETS[i % INTERNAL_SUBNETS.length];
    const host = 10 + ((i * 7 + seed) % 240);
    const ip = `${subnet}.${host}`;
    if (ip === subjectIp || nodeMap.has(ip)) continue;
    nodeMap.set(ip, {
      id: ip,
      ip,
      port: null,
      flow_count: Math.round(320 + pseudoRandom(seed, i) * 4200),
      is_internal: true,
    });
  }

  for (let i = 0; i < 22; i += 1) {
    const prefix = EXTERNAL_IP_PREFIXES[i % EXTERNAL_IP_PREFIXES.length];
    const ip = `${prefix}.${20 + i}`;
    nodeMap.set(ip, {
      id: ip,
      ip,
      port: null,
      flow_count: Math.round(680 + pseudoRandom(seed, i + 100) * 5200),
      is_internal: false,
    });
  }

  const nodes = [...nodeMap.values()];
  const nodeIds = nodes.map((node) => node.id);
  const links: TopologyGraph["links"] = [];

  const externalIds = nodes.filter((node) => !node.is_internal).map((node) => node.id);
  const internalIds = nodes.filter((node) => node.is_internal).map((node) => node.id);

  externalIds.slice(0, 8).forEach((target, index) => {
    links.push({
      source: subjectIp,
      target,
      value: Math.round(900 + pseudoRandom(seed, index + 200) * 4800),
      is_benign: false,
    });
  });

  internalIds
    .filter((id) => id !== subjectIp)
    .slice(0, 14)
    .forEach((target, index) => {
      links.push({
        source: subjectIp,
        target,
        value: Math.round(180 + pseudoRandom(seed, index + 300) * 1600),
        is_benign: true,
      });
    });

  for (let i = 0; i < 48; i += 1) {
    const source = nodeIds[Math.floor(pseudoRandom(seed, i + 400) * nodeIds.length)];
    let target = nodeIds[Math.floor(pseudoRandom(seed, i + 500) * nodeIds.length)];
    if (source === target) {
      target = nodeIds[(nodeIds.indexOf(source) + 1) % nodeIds.length];
    }
    const sourceInternal = isInternalIp(source);
    const targetInternal = isInternalIp(target);
    links.push({
      source,
      target,
      value: Math.round(60 + pseudoRandom(seed, i + 600) * 1200),
      is_benign: sourceInternal && targetInternal,
    });
  }

  const dedupedLinks = new Map<string, TopologyGraph["links"][number]>();
  links.forEach((link) => {
    const key = `${link.source}->${link.target}`;
    const existing = dedupedLinks.get(key);
    if (existing) {
      existing.value += link.value;
      return;
    }
    dedupedLinks.set(key, { ...link });
  });

  const finalLinks = [...dedupedLinks.values()];
  const totalFlows = finalLinks.reduce((sum, link) => sum + link.value, 0);

  return {
    flow_count: totalFlows,
    node_mode: "host",
    nodes,
    links: finalLinks,
    stats: { top_dst_port: 443, top_dst_port_ratio: 0.54 + seed * 0.03 },
  };
}

function buildMockEndpointGraph(subjectIp: string, seed: number): TopologyGraph {
  const endpointId = (ip: string, port: number) => `${ip}:${port}`;
  const nodeMap = new Map<
    string,
    {
      id: string;
      ip: string;
      port: number;
      flow_count: number;
      is_internal: boolean;
    }
  >();

  const registerEndpoint = (ip: string, port: number, flowBoost = 0) => {
    const id = endpointId(ip, port);
    if (nodeMap.has(id)) return id;
    nodeMap.set(id, {
      id,
      ip,
      port,
      flow_count: Math.round(240 + pseudoRandom(seed, port + flowBoost) * 3600),
      is_internal: isInternalIp(ip),
    });
    return id;
  };

  COMMON_PORTS.forEach((port, index) => {
    registerEndpoint(subjectIp, port, index + 10);
  });

  INTERNAL_SUBNETS.forEach((subnet, subnetIndex) => {
    for (let i = 0; i < 4; i += 1) {
      const ip = `${subnet}.${20 + subnetIndex * 4 + i}`;
      COMMON_PORTS.slice(0, 3 + (i % 3)).forEach((port, portIndex) => {
        registerEndpoint(ip, port, subnetIndex * 10 + portIndex);
      });
    }
  });

  EXTERNAL_IP_PREFIXES.forEach((prefix, prefixIndex) => {
    for (let i = 0; i < 3; i += 1) {
      const ip = `${prefix}.${30 + prefixIndex * 3 + i}`;
      [443, 8443, 8080, 53].forEach((port, portIndex) => {
        registerEndpoint(ip, port, prefixIndex * 20 + portIndex);
      });
    }
  });

  const nodes = [...nodeMap.values()];
  const links: TopologyGraph["links"] = [];
  const subjectEndpoints = nodes.filter((node) => node.ip === subjectIp).map((node) => node.id);
  const externalEndpoints = nodes.filter((node) => !node.is_internal).map((node) => node.id);
  const internalEndpoints = nodes
    .filter((node) => node.is_internal && node.ip !== subjectIp)
    .map((node) => node.id);

  subjectEndpoints.forEach((source, index) => {
    externalEndpoints.slice(0, 6).forEach((target, targetIndex) => {
      links.push({
        source,
        target,
        value: Math.round(420 + pseudoRandom(seed, index * 20 + targetIndex) * 3200),
        is_benign: false,
      });
    });
  });

  subjectEndpoints.slice(0, 4).forEach((source, index) => {
    internalEndpoints.slice(0, 8).forEach((target, targetIndex) => {
      links.push({
        source,
        target,
        value: Math.round(90 + pseudoRandom(seed, index * 30 + targetIndex) * 900),
        is_benign: true,
      });
    });
  });

  for (let i = 0; i < 72; i += 1) {
    const source = nodes[Math.floor(pseudoRandom(seed, i + 700) * nodes.length)]?.id;
    let target = nodes[Math.floor(pseudoRandom(seed, i + 800) * nodes.length)]?.id;
    if (!source || !target || source === target) continue;
    const sourceNode = nodeMap.get(source);
    const targetNode = nodeMap.get(target);
    links.push({
      source,
      target,
      value: Math.round(40 + pseudoRandom(seed, i + 900) * 800),
      is_benign: Boolean(sourceNode?.is_internal && targetNode?.is_internal),
    });
  }

  const dedupedLinks = new Map<string, TopologyGraph["links"][number]>();
  links.forEach((link) => {
    const key = `${link.source}->${link.target}`;
    const existing = dedupedLinks.get(key);
    if (existing) {
      existing.value += link.value;
      return;
    }
    dedupedLinks.set(key, { ...link });
  });

  const finalLinks = [...dedupedLinks.values()];

  return {
    flow_count: finalLinks.reduce((sum, link) => sum + link.value, 0),
    node_mode: "endpoint",
    nodes,
    links: finalLinks,
    stats: { top_dst_port: 443, top_dst_port_ratio: 0.63 },
  };
}

/** 风险关联网络拓扑 mock（结构与总览页 dataset_network_topology.json 一致） */
export function getMockRiskNetworkTopology(
  riskId: number
): DatasetNetworkTopologyJson | null {
  const risk = getMockRiskById(riskId);
  if (!risk) return null;

  const seed = riskId % 5;
  const host = buildMockHostGraph(risk.subjectIp, seed);
  const endpoint = buildMockEndpointGraph(risk.subjectIp, seed);

  return {
    version: 1,
    total_flows: host.flow_count,
    labels: [],
    default_label: "__combined__",
    default_node_mode: "host",
    aggregate_views: ["__combined__"],
    views: {
      __combined__: {
        label: "__combined__",
        view_kind: "aggregate",
        is_benign: null,
        host,
        endpoint,
      },
    },
  };
}

/** @deprecated 使用 getMockRiskById */
export function getMockTaskById(id: number): RiskItem | undefined {
  return getMockRiskById(id);
}
