import type { RiskTrafficLogItem } from "@/api/services/RiskService";
import type { FlowDetail } from "@/api/services/RiskService";
import type {
  TrafficLogDetail,
  TrafficLogDetailSection,
  TrafficLogInterfaceBlock,
  TrafficLogInterfaceDetail,
} from "@/types/trafficLogDetail";
import { formatTrafficVolumeText } from "@/utils/formatTotalTraffic";

function formatPort(port: number): string {
  return port > 0 ? String(port) : "-";
}

function isInternalIp(ip: string): boolean {
  return (
    ip.startsWith("10.") ||
    ip.startsWith("192.168.") ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(ip)
  );
}

function ipWithTag(ip: string): { value: string; tag?: string } {
  if (!ip || ip === "-") {
    return { value: "-" };
  }
  return {
    value: ip,
    tag: isInternalIp(ip) ? "内网" : "外网",
  };
}

/** 基于列表行数据生成详情 mock（后续可替换为接口） */
export function buildMockTrafficLogDetail(
  log: RiskTrafficLogItem,
): TrafficLogDetail {
  const src = ipWithTag(log.srcIp);
  const dst = ipWithTag(log.dstIp);
  const trafficText = formatTrafficVolumeText(log.traffic);

  return {
    id: log.id,
    accessTime: log.accessTime || "-",
    traffic: trafficText,
    logSource: "流量引擎-黑胡桃-流量引擎",
    appName: "300-聚合-2",
    userVisitAddress: `${log.dstIp}:${formatPort(log.dstPort)}`,
    path: "/data/3333/11111/111/222/1121",
    visitDomain: "局域网-默认局域网 (ABC类)",
    deployDomain: "局域网-默认局域网 (ABC类)",
    visitAccount: "-",
    userName: "-",
    srcIp: src.value,
    srcIpTag: src.tag,
    srcPort: formatPort(log.srcPort),
    protocol: log.protocol || "-",
    dstIp: dst.value,
    dstIpTag: dst.tag,
    dstPort: formatPort(log.dstPort),
    apiMethod: "GET",
    apiProtocol: "RESTful",
    visitBusiness: "300-聚合-2",
    requestSize: "811B",
    macAddress: "-",
    referer: "-",
    xffIp: "-",
    requestDataTag: "-",
    identifiedFile: "-",
    responseStatus: "200 OK",
    responseSize: trafficText,
    responseDataTag: "-",
    contentType: "application/json",
    responseTime: "12ms",
  };
}

function formatFlowTime(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function protocolName(protocol: unknown, appProto: unknown, fallback: string): string {
  const app = typeof appProto === "string" ? appProto.trim() : "";
  if (app) return app.toUpperCase();
  const numeric = Number(protocol);
  if (numeric === 6) return "TCP";
  if (numeric === 17) return "UDP";
  if (numeric === 1) return "ICMP";
  return fallback || "-";
}

export function buildTrafficLogDetailFromFlow(
  log: RiskTrafficLogItem,
  flow: FlowDetail | null,
): TrafficLogDetail {
  const base = buildMockTrafficLogDetail(log);
  if (!flow) return base;
  const srcIp = flow.src_ip || log.srcIp;
  const dstIp = flow.dst_ip || log.dstIp;
  const src = ipWithTag(srcIp);
  const dst = ipWithTag(dstIp);
  const srcPort = Number(flow.src_port ?? log.srcPort);
  const dstPort = Number(flow.dst_port ?? log.dstPort);
  const trafficText = formatTrafficVolumeText(Number(flow.total_bytes ?? log.traffic));
  const payload = flow.payload;

  return {
    ...base,
    id: flow.flow_uid || log.id,
    accessTime: formatFlowTime(flow.event_time, log.accessTime || "-"),
    traffic: trafficText,
    userVisitAddress: `${dstIp}:${formatPort(dstPort)}`,
    srcIp: src.value,
    srcIpTag: src.tag,
    srcPort: formatPort(srcPort),
    protocol: protocolName(flow.protocol, flow.app_proto, log.protocol),
    dstIp: dst.value,
    dstIpTag: dst.tag,
    dstPort: formatPort(dstPort),
    responseSize: trafficText,
    payloadSample: payload
      ? {
          encoding: payload.encoding || "base64",
          sampleB64: payload.sample_b64 || "",
          sampleBytes: Number(payload.sample_bytes || 0),
          originalBytes: Number(payload.original_bytes || 0),
          truncated: Boolean(payload.truncated),
          direction: payload.direction || "",
        }
      : undefined,
  };
}

function formatPayloadDirection(direction: string): string {
  const normalized = direction.trim().toLowerCase();
  if (normalized === "toserver") return "发往服务端";
  if (normalized === "toclient") return "发往客户端";
  return direction || "-";
}

function formatPayloadStatus(truncated: boolean): string {
  return truncated ? "已采样" : "完整样本";
}

function buildPayloadSampleFields(
  sample: NonNullable<TrafficLogDetail["payloadSample"]>,
): TrafficLogDetailSection["fields"] {
  return [
    { label: "编码", value: sample.encoding || "base64" },
    { label: "方向", value: formatPayloadDirection(sample.direction) },
    { label: "采样字节数", value: String(sample.sampleBytes) },
    { label: "原始字节数", value: String(sample.originalBytes) },
    { label: "状态", value: formatPayloadStatus(sample.truncated) },
  ];
}

export function buildBasicInfoSections(
  detail: TrafficLogDetail,
): TrafficLogDetailSection[] {
  const sections: TrafficLogDetailSection[] = [
    {
      title: "基础信息",
      fields: [
        { label: "访问时间", value: detail.accessTime },
        { label: "流量", value: detail.traffic },
        // { label: "日志来源", value: detail.logSource },
        // { label: "应用名称", value: detail.appName },
        // { label: "用户访问地址", value: detail.userVisitAddress },
        // { label: "路径", value: detail.path },
        // { label: "访问域", value: detail.visitDomain },
        // { label: "部署域", value: detail.deployDomain },
        // {
        //   label: "访问账号",
        //   value: detail.visitAccount,
        //   hint: "暂无账号识别结果",
        // },
        // {
        //   label: "用户名称",
        //   value: detail.userName,
        //   hint: "暂无用户识别结果",
        // },
      ],
    },
    {
      title: "五元组信息",
      fields: [
        {
          label: "源IP",
          value: detail.srcIpTag
            ? `${detail.srcIp} (${detail.srcIpTag})`
            : detail.srcIp,
        },
        { label: "源端口", value: detail.srcPort },
        { label: "协议类型", value: detail.protocol },
        {
          label: "目的IP",
          value: detail.dstIpTag
            ? `${detail.dstIp} (${detail.dstIpTag})`
            : detail.dstIp,
        },
        { label: "目的端口", value: detail.dstPort },
      ],
    },
  ];

  if (detail.payloadSample) {
    sections.push({
      title: "采样信息",
      fields: buildPayloadSampleFields(detail.payloadSample),
    });
  }

  sections.push({
    title: "报文信息",
    fields: [],
    messageBlock: buildTrafficLogRequestBlock(detail),
  });

  return sections;
}

function buildRequestReqRaw(_detail: TrafficLogDetail): string {
  if (_detail.payloadSample) {
    return _detail.payloadSample.sampleB64 || "-";
  }
  // const host = detail.userVisitAddress.split(":")[0] || detail.dstIp;
  // const port = detail.userVisitAddress.split(":")[1] || detail.dstPort;
  return [
    `-`
    // `${detail.apiMethod} ${detail.path} HTTP/1.1`,
    // `Host: ${host}:${port}`,
    // `User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36`,
    // `Accept: application/json, text/plain, */*`,
    // `Accept-Language: zh-CN,zh;q=0.9,en;q=0.8`,
    // `Accept-Encoding: gzip, deflate`,
    // `Connection: keep-alive`,
    // `Referer: ${detail.referer === "-" ? "-" : detail.referer}`,
    // `X-Forwarded-For: ${detail.xffIp === "-" ? "-" : detail.xffIp}`,
    // `Cookie: session_id=mock_session_${detail.accessTime.replace(/\D/g, "").slice(0, 8)}`,
    // ``,
  ].join("\n");
}

function decodeBase64Bytes(value: string): number[] {
  if (!value) return [];
  try {
    if (typeof atob === "function") {
      const raw = atob(value);
      return Array.from(raw, (char) => char.charCodeAt(0));
    }
  } catch {
    return [];
  }
  return [];
}

function formatHex(bytes: number[]): string {
  if (!bytes.length) return "-";
  const lines: string[] = [];
  for (let offset = 0; offset < bytes.length; offset += 16) {
    const chunk = bytes.slice(offset, offset + 16);
    lines.push(
      `${offset.toString(16).padStart(4, "0")}  ${chunk
        .map((byte) => byte.toString(16).padStart(2, "0"))
        .join(" ")}`,
    );
  }
  return lines.join("\n");
}

function formatPrintable(bytes: number[]): string {
  if (!bytes.length) return "-";
  let out = "";
  for (const byte of bytes) {
    out += byte >= 32 && byte <= 126 ? String.fromCharCode(byte) : ".";
  }
  return out;
}

function buildRequestBody(): string {
  return "";
}

function buildRequestHeader(detail: TrafficLogDetail): string {
  return [
    `method: ${detail.apiMethod}`,
    `path: ${detail.path}`,
    `scheme: http`,
    `authority: ${detail.userVisitAddress}`,
    `user-agent: Mozilla/5.0`,
    `accept: */*`,
    `accept-encoding: gzip, deflate`,
    `accept-language: zh-CN,zh;q=0.9`,
  ].join("\n");
}

function buildResponseResRaw(detail: TrafficLogDetail): string {
  return [
    `HTTP/1.1 ${detail.responseStatus}`,
    `Content-Type: ${detail.contentType}`,
    `Content-Length: ${detail.responseSize}`,
    `Connection: keep-alive`,
    `Date: ${detail.accessTime}`,
    `Server: nginx/1.18.0`,
    `X-Response-Time: ${detail.responseTime}`,
    ``,
    `[`,
    `  {`,
    `    "id": 10001,`,
    `    "name": "示例数据",`,
    `    "status": "ok"`,
    `  }`,
    `]`,
  ].join("\n");
}

function buildResponseBody(): string {
  return `[\n  {\n    "id": 10001,\n    "name": "示例数据",\n    "status": "ok"\n  }\n]`;
}

function buildResponseHeader(detail: TrafficLogDetail): string {
  return [
    `status: ${detail.responseStatus}`,
    `content-type: ${detail.contentType}`,
    `content-length: ${detail.responseSize}`,
    `connection: keep-alive`,
    `date: ${detail.accessTime}`,
    `server: nginx/1.18.0`,
    `x-response-time: ${detail.responseTime}`,
  ].join("\n");
}

function buildTrafficLogRequestBlock(
  detail: TrafficLogDetail,
): TrafficLogInterfaceBlock {
  return {
    titlePrefix: "请求",
    sizeLabel: detail.requestSize,
    defaultPaneKey: "req-raw",
    panes: [
      {
        key: "req-raw",
        label: detail.payloadSample ? "Base64" : "Req-Raw",
        content: buildRequestReqRaw(detail),
      },
      {
        key: "hex",
        label: "Hex",
        content: detail.payloadSample
          ? formatHex(decodeBase64Bytes(detail.payloadSample.sampleB64))
          : buildRequestBody(),
      },
      {
        key: "printable",
        label: "Printable",
        content: detail.payloadSample
          ? formatPrintable(decodeBase64Bytes(detail.payloadSample.sampleB64))
          : buildRequestHeader(detail),
      },
    ],
  };
}

/** 接口详情 Tab mock（请求/响应 Raw 等） */
export function buildMockTrafficLogInterfaceDetail(
  detail: TrafficLogDetail,
): TrafficLogInterfaceDetail {
  return {
    request: buildTrafficLogRequestBlock(detail),
    response: {
      titlePrefix: "响应",
      sizeLabel: detail.responseSize,
      defaultPaneKey: "res-raw",
      // dataTags: MOCK_RESPONSE_DATA_TAGS,
      panes: [
        {
          key: "res-raw",
          label: "Res-Raw",
          content: buildResponseResRaw(detail),
        },
        { key: "body", label: "Body", content: buildResponseBody() },
        {
          key: "header",
          label: "Header",
          content: buildResponseHeader(detail),
        },
      ],
    },
  };
}
