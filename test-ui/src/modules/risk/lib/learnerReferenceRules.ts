import type { LearnerMetricAuditItem } from '../types/learnerTopology'

export type LearnerReferenceRuleMatch = {
  key: string
  name: string
  tone: 'benign' | 'attack' | 'caution'
  semantic: string
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

function hasFixedTargetServiceCore(scores: MetricScores): boolean {
  return (
    atMost(scores, 'dst_port_entropy', 12) &&
    atMost(scores, 'dst_port_richness', 30) &&
    atLeast(scores, 'dst_port_top1_concentration', 95) &&
    atLeast(scores, 'endpoint_edge_entropy', 80) &&
    atLeast(scores, 'src_port_entropy', 80)
  )
}

function hasFixedTargetSupport(scores: MetricScores): boolean {
  return (
    atLeast(scores, 'dst_host_concentration', 65) ||
    atLeast(scores, 'max_in_degree_ratio', 75) ||
    atLeast(scores, 'host_max_in_degree_ratio', 75)
  )
}

function isFixedTargetServiceAttack(scores: MetricScores): boolean {
  return hasFixedTargetServiceCore(scores) && hasFixedTargetSupport(scores)
}

function isDiffuseOneWayAttack(scores: MetricScores): boolean {
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
    key: 'benign-natural-dispersion',
    name: '正常流量参考匹配',
    tone: 'benign',
    semantic:
      '边分布较散、无单边支配，目的端口丰富度处于常见服务混合范围，流内单向性也不极端。',
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
    key: 'fixed-service-dos-ddos-family',
    name: 'DoS/DDoS 等固定服务攻击族',
    tone: 'attack',
    semantic:
      '该形态与 DoS/DDoS 及其他固定服务攻击族相近：目的服务几乎固定，大量变化源端指向少数目的 endpoint。',
    match: isFixedTargetServiceAttack,
  },
  {
    key: 'slow-dos-fixed-service',
    name: 'Slow DoS 类攻击参考匹配',
    tone: 'attack',
    semantic:
      '固定目的服务汇聚仍明显，同时流内单向性更强，提示慢速或低反馈的服务冲击行为。',
    match: (s) => isFixedTargetServiceAttack(s) && atLeast(s, 'low_reciprocity', 68),
  },
  {
    key: 'portscan-wide-target',
    name: 'PortScan 类攻击参考匹配',
    tone: 'attack',
    semantic:
      '目的端口丰富度和分布熵同时偏高，目的 endpoint 大范围展开，单一服务不占主导。',
    match: (s) =>
      atLeast(s, 'dst_port_entropy', 90) &&
      atLeast(s, 'dst_port_richness', 70) &&
      atMost(s, 'dst_port_top1_concentration', 15) &&
      atMost(s, 'dst_endpoint_concentration', 15) &&
      atLeast(s, 'endpoint_edge_entropy', 90) &&
      atMost(s, 'low_reciprocity', 75),
  },
  {
    key: 'heartbleed-like-small-sample',
    name: 'Heartbleed 小样本参考匹配',
    tone: 'caution',
    semantic:
      '少量流集中在极少边上；这类小样本形态只适合作为人工复核提示。',
    match: (s) =>
      atMost(s, 'endpoint_edge_entropy', 20) &&
      atLeast(s, 'top1_endpoint_edge_share', 80) &&
      atLeast(s, 'dst_port_top1_concentration', 95) &&
      atMost(s, 'src_port_entropy', 25),
  },
  {
    key: 'diffuse-one-way-drdos-udp-syn-family',
    name: 'DRDoS/UDP/SYN 单向攻击族',
    tone: 'attack',
    semantic:
      '该形态与 DRDoS、UDP/SYN 冲击族相近：目的端口高度分散，边接近一次性，流记录内强单向。',
    match: isDiffuseOneWayAttack,
  },
  {
    key: 'drdos-dns-ldap-ntp-like',
    name: 'DRDoS DNS/LDAP/NTP 类参考匹配',
    tone: 'attack',
    semantic:
      '在高分散单向形态上，源端口分散度处于中高区间，提示一类较稳定的端口展开模式。',
    match: (s) => isDiffuseOneWayAttack(s) && between(s, 'src_port_entropy', 65, 85),
  },
  {
    key: 'drdos-snmp-ssdp-tftp-like',
    name: 'DRDoS SNMP/SSDP/TFTP 类参考匹配',
    tone: 'attack',
    semantic:
      '在高分散单向形态上，源端口分散度更高，提示源端口展开更充分的子形态。',
    match: (s) => isDiffuseOneWayAttack(s) && between(s, 'src_port_entropy', 85, 98),
  },
  {
    key: 'drdos-udp-syn-udp-lag-like',
    name: 'DRDoS UDP/SYN/UDP-LAG 类参考匹配',
    tone: 'attack',
    semantic:
      '在高分散单向形态上，源端口也极分散，提示源端和目的端同时高度展开。',
    match: (s) => isDiffuseOneWayAttack(s) && atLeast(s, 'src_port_entropy', 98),
  },
  {
    key: 'web-ddos-bidirectional-hub-like',
    name: 'WebDDoS 类攻击参考匹配',
    tone: 'caution',
    semantic:
      '目的端口没有全局扫散，但入向和出向 hub 同时明显，提示围绕服务节点的双向冲击结构。',
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
    tone: rule.tone,
    semantic: rule.semantic,
  }))
}
