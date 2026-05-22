import type { LearnerMetricAuditItem } from '../types/learnerTopology'

export type LearnerReferenceRuleMatch = {
  key: string
  name: string
  dataset: 'CICIDS2017' | 'CICIDS2019' | 'CICIDS2017/2019'
  tone: 'benign' | 'attack' | 'caution'
  semantic: string
  referenceLabels: string[]
}

type MetricScores = Record<string, number | undefined>

type LearnerReferenceRule = LearnerReferenceRuleMatch & {
  match: (scores: MetricScores) => boolean
}

function scoreMap(metrics: LearnerMetricAuditItem[]): MetricScores {
  return Object.fromEntries(
    metrics
      .filter((m) => Number.isFinite(m.score_0_100))
      .map((m) => [m.metric_key, m.score_0_100]),
  )
}

function atLeast(scores: MetricScores, key: string, min: number): boolean {
  const value = scores[key]
  return Number.isFinite(value) && Number(value) >= min
}

function atMost(scores: MetricScores, key: string, max: number): boolean {
  const value = scores[key]
  return Number.isFinite(value) && Number(value) <= max
}

function between(scores: MetricScores, key: string, min: number, max: number): boolean {
  return atLeast(scores, key, min) && atMost(scores, key, max)
}

function isFixedTarget2017(scores: MetricScores): boolean {
  return (
    atMost(scores, 'dst_port_entropy', 12) &&
    atMost(scores, 'dst_port_richness', 30) &&
    atLeast(scores, 'dst_port_top1_concentration', 95) &&
    atLeast(scores, 'dst_host_concentration', 85) &&
    atLeast(scores, 'host_max_in_degree_ratio', 85) &&
    atLeast(scores, 'endpoint_edge_entropy', 80) &&
    atLeast(scores, 'src_port_entropy', 80)
  )
}

function isDiffuseOneWay2019(scores: MetricScores): boolean {
  return (
    atLeast(scores, 'dst_port_entropy', 90) &&
    atLeast(scores, 'dst_port_richness', 90) &&
    atMost(scores, 'dst_port_top1_concentration', 10) &&
    atLeast(scores, 'endpoint_edge_entropy', 95) &&
    atMost(scores, 'edge_reuse_ratio', 25) &&
    atLeast(scores, 'low_reciprocity', 85)
  )
}

const REFERENCE_RULES: LearnerReferenceRule[] = [
  {
    key: 'cicids-benign-reference',
    name: '自然分散流量形态',
    dataset: 'CICIDS2017/2019',
    tone: 'benign',
    semantic:
      '边分布较散、无单边支配，目的端口丰富度处于常见服务混合范围，流内单向性也不极端。',
    referenceLabels: ['2017|BENIGN', '2019|BENIGN'],
    match: (s) =>
      atLeast(s, 'endpoint_edge_entropy', 82) &&
      atMost(s, 'top1_endpoint_edge_share', 8) &&
      between(s, 'edge_reuse_ratio', 35, 65) &&
      atMost(s, 'dst_port_entropy', 45) &&
      atMost(s, 'dst_port_richness', 75) &&
      between(s, 'dst_port_top1_concentration', 20, 85) &&
      atMost(s, 'low_reciprocity', 70) &&
      atMost(s, 'max_out_degree_ratio', 15),
  },
  {
    key: 'cicids2017-fixed-target-service',
    name: '固定目的服务冲击形态',
    dataset: 'CICIDS2017',
    tone: 'attack',
    semantic:
      '目的服务几乎固定，大量变化源端指向少数目的 endpoint；边熵高也可能来自源端展开。',
    referenceLabels: [
      '2017|DDOS',
      '2017|DOS_HULK',
      '2017|DOS_GOLDENEYE',
      '2017|FTP-PATATOR',
      '2017|SSH-PATATOR',
      '2017|BOTNET',
      '2017|WEB_ATTACK_*',
    ],
    match: isFixedTarget2017,
  },
  {
    key: 'cicids2017-slow-dos',
    name: '固定目的慢速冲击形态',
    dataset: 'CICIDS2017',
    tone: 'attack',
    semantic:
      '仍是固定目的服务形态，但流内单向性更强，提示慢速或低反馈的服务冲击行为。',
    referenceLabels: ['2017|DOS_SLOWHTTPTEST', '2017|DOS_SLOWLORIS'],
    match: (s) => isFixedTarget2017(s) && atLeast(s, 'low_reciprocity', 68),
  },
  {
    key: 'cicids2017-portscan',
    name: '端口扫描形态',
    dataset: 'CICIDS2017',
    tone: 'attack',
    semantic:
      '目的端口丰富度和分布熵同时偏高，目的 endpoint 大范围展开，单一服务不占主导。',
    referenceLabels: ['2017|PORTSCAN', '2017|INFILTRATION_-_PORTSCAN'],
    match: (s) =>
      atLeast(s, 'dst_port_entropy', 90) &&
      atLeast(s, 'dst_port_richness', 70) &&
      atMost(s, 'dst_port_top1_concentration', 15) &&
      atMost(s, 'dst_endpoint_concentration', 15) &&
      atLeast(s, 'endpoint_edge_entropy', 90) &&
      atMost(s, 'low_reciprocity', 75),
  },
  {
    key: 'cicids2017-single-edge-small-sample',
    name: '固定单边小样本形态',
    dataset: 'CICIDS2017',
    tone: 'caution',
    semantic:
      '少量流集中在极少边上；这类小样本形态只适合作为人工复核提示。',
    referenceLabels: ['2017|HEARTBLEED'],
    match: (s) =>
      atMost(s, 'endpoint_edge_entropy', 20) &&
      atLeast(s, 'top1_endpoint_edge_share', 80) &&
      atLeast(s, 'dst_port_top1_concentration', 95) &&
      atMost(s, 'src_port_entropy', 25),
  },
  {
    key: 'cicids2019-diffuse-one-way',
    name: '高分散单向冲击形态',
    dataset: 'CICIDS2019',
    tone: 'attack',
    semantic:
      '目的端口高度分散，边接近一次性，流记录内强单向，提示高并发的分散式冲击行为。',
    referenceLabels: [
      '2019|DRDOS_DNS',
      '2019|DRDOS_LDAP',
      '2019|DRDOS_MSSQL',
      '2019|DRDOS_NETBIOS',
      '2019|DRDOS_NTP',
      '2019|DRDOS_SNMP',
      '2019|DRDOS_SSDP',
      '2019|DRDOS_UDP',
      '2019|SYN',
      '2019|TFTP',
      '2019|UDP-LAG',
    ],
    match: isDiffuseOneWay2019,
  },
  {
    key: 'cicids2019-drdos-mid-src-port',
    name: '中源端口分散子形态',
    dataset: 'CICIDS2019',
    tone: 'attack',
    semantic:
      '在高分散单向形态上，源端口分散度处于中高区间，提示一类较稳定的端口展开模式。',
    referenceLabels: [
      '2019|DRDOS_DNS',
      '2019|DRDOS_LDAP',
      '2019|DRDOS_MSSQL',
      '2019|DRDOS_NETBIOS',
      '2019|DRDOS_NTP',
    ],
    match: (s) => isDiffuseOneWay2019(s) && between(s, 'src_port_entropy', 65, 85),
  },
  {
    key: 'cicids2019-drdos-high-src-port',
    name: '高源端口分散子形态',
    dataset: 'CICIDS2019',
    tone: 'attack',
    semantic:
      '在高分散单向形态上，源端口分散度更高，提示源端口展开更充分的子形态。',
    referenceLabels: ['2019|DRDOS_SNMP', '2019|DRDOS_SSDP', '2019|TFTP'],
    match: (s) => isDiffuseOneWay2019(s) && between(s, 'src_port_entropy', 85, 98),
  },
  {
    key: 'cicids2019-udp-syn-highest-src-port',
    name: '极高源端口分散子形态',
    dataset: 'CICIDS2019',
    tone: 'attack',
    semantic:
      '在高分散单向形态上，源端口也极分散，提示源端和目的端同时高度展开。',
    referenceLabels: ['2019|DRDOS_UDP', '2019|SYN', '2019|UDP-LAG'],
    match: (s) => isDiffuseOneWay2019(s) && atLeast(s, 'src_port_entropy', 98),
  },
  {
    key: 'cicids2019-webddos',
    name: '双向 Hub 服务冲击形态',
    dataset: 'CICIDS2019',
    tone: 'caution',
    semantic:
      '目的端口没有全局扫散，但入向和出向 hub 同时明显，提示围绕服务节点的双向冲击结构。',
    referenceLabels: ['2019|WEBDDOS'],
    match: (s) =>
      between(s, 'dst_port_entropy', 35, 65) &&
      between(s, 'dst_port_top1_concentration', 50, 85) &&
      atLeast(s, 'max_in_degree_ratio', 80) &&
      atLeast(s, 'max_out_degree_ratio', 80) &&
      atLeast(s, 'endpoint_edge_entropy', 90),
  },
]

export function evaluateLearnerReferenceRules(
  metrics: LearnerMetricAuditItem[],
): LearnerReferenceRuleMatch[] {
  const scores = scoreMap(metrics)
  return REFERENCE_RULES.filter((rule) => rule.match(scores)).map((rule) => ({
    key: rule.key,
    name: rule.name,
    dataset: rule.dataset,
    tone: rule.tone,
    semantic: rule.semantic,
    referenceLabels: rule.referenceLabels,
  }))
}
