import type {
  DatasetNetworkTopologyJson,
  TopologyGraph,
  TopologyLabelView,
  TopologyLink,
} from "@/components/NetworkTopologyPanel";

const OVERVIEW_HUB_IP = "10.12.45.88";

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

function buildMockHostGraph(subjectIp: string, seed: number): TopologyGraph {
  const internal = isInternalIp(subjectIp);
  const nodeMap = new Map<string, TopologyGraph["nodes"][number]>();

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
  const links: TopologyLink[] = [];

  const externalIds = nodes
    .filter((node) => !node.is_internal)
    .map((node) => node.id);
  const internalIds = nodes
    .filter((node) => node.is_internal)
    .map((node) => node.id);

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

  const dedupedLinks = new Map<string, TopologyLink>();
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
    stats: { top_dst_port: 443, top_dst_port_ratio: 0.54 },
  };
}

function buildMockEndpointGraph(subjectIp: string, seed: number): TopologyGraph {
  const endpointId = (ip: string, port: number) => `${ip}:${port}`;
  const nodeMap = new Map<string, TopologyGraph["nodes"][number]>();

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
  const links: TopologyLink[] = [];
  const subjectEndpoints = nodes
    .filter((node) => node.ip === subjectIp)
    .map((node) => node.id);
  const externalEndpoints = nodes
    .filter((node) => !node.is_internal)
    .map((node) => node.id);
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

  const dedupedLinks = new Map<string, TopologyLink>();
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

function pruneGraphByEdgeType(
  graph: TopologyGraph,
  mode: "benign" | "attack",
): TopologyGraph {
  const links = graph.links.filter((link) =>
    mode === "benign" ? link.is_benign !== false : link.is_benign === false,
  );
  const nodeIds = new Set<string>();
  links.forEach((link) => {
    nodeIds.add(link.source);
    nodeIds.add(link.target);
  });
  const nodes = graph.nodes.filter((node) => nodeIds.has(node.id));

  return {
    ...graph,
    nodes,
    links,
    flow_count: links.reduce((sum, link) => sum + link.value, 0),
  };
}

function buildLabelView(
  host: TopologyGraph,
  endpoint: TopologyGraph,
  isBenign: boolean | null,
): TopologyLabelView {
  return {
    label: isBenign === null ? "__combined__" : isBenign ? "__benign__" : "__attack__",
    view_kind: "aggregate",
    is_benign: isBenign,
    host,
    endpoint,
  };
}

/** 总览页网络拓扑 mock（总 / 良性 / 攻击） */
export function getMockOverviewNetworkTopology(): DatasetNetworkTopologyJson {
  const seed = 3;
  const combinedHost = buildMockHostGraph(OVERVIEW_HUB_IP, seed);
  const combinedEndpoint = buildMockEndpointGraph(OVERVIEW_HUB_IP, seed);

  const benignHost = pruneGraphByEdgeType(combinedHost, "benign");
  const benignEndpoint = pruneGraphByEdgeType(combinedEndpoint, "benign");
  const attackHost = pruneGraphByEdgeType(combinedHost, "attack");
  const attackEndpoint = pruneGraphByEdgeType(combinedEndpoint, "attack");

  return {
    version: 1,
    total_flows: combinedHost.flow_count,
    labels: [],
    default_label: "__combined__",
    default_node_mode: "host",
    aggregate_views: ["__combined__", "__benign__", "__attack__"],
    views: {
      __combined__: buildLabelView(combinedHost, combinedEndpoint, null),
      __benign__: buildLabelView(benignHost, benignEndpoint, true),
      __attack__: buildLabelView(attackHost, attackEndpoint, false),
    },
  };
}
