import type { RiskTrafficLogItem } from "@/api/services/RiskService";
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

export function buildBasicInfoSections(
  detail: TrafficLogDetail,
): TrafficLogDetailSection[] {
  return [
    // {
    //   title: "基础信息",
    //   fields: [
    //     { label: "访问时间", value: detail.accessTime },
    //     { label: "流量", value: detail.traffic },
    //     { label: "日志来源", value: detail.logSource },
    //     { label: "应用名称", value: detail.appName },
    //     { label: "用户访问地址", value: detail.userVisitAddress },
    //     { label: "路径", value: detail.path },
    //     { label: "访问域", value: detail.visitDomain },
    //     { label: "部署域", value: detail.deployDomain },
    //     {
    //       label: "访问账号",
    //       value: detail.visitAccount,
    //       hint: "暂无账号识别结果",
    //     },
    //     {
    //       label: "用户名称",
    //       value: detail.userName,
    //       hint: "暂无用户识别结果",
    //     },
    //   ],
    // },
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
    {
      title: "报文信息",
      fields: [],
      messageBlock: buildTrafficLogRequestBlock(detail),
    },
  ];
}

function buildRequestReqRaw(detail: TrafficLogDetail): string {
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

function buildRequestQueryParams(): string {
  return "page=1\nlimit=20\nsort=desc";
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

const MOCK_RESPONSE_DATA_TAGS = [
  "服务人员姓名(1)",
  "年龄(1)",
  "出生日期(1)",
  "性别(1)",
  "身份证号(1)",
  "手机号码(1)",
  "联系地址(1)",
  "电子邮箱(1)",
];

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
        label: "Req-Raw",
        content: buildRequestReqRaw(detail),
      },
      { key: "body", label: "Body", content: buildRequestBody() },
      {
        key: "header",
        label: "Header",
        content: buildRequestHeader(detail),
      },
      {
        key: "query",
        label: "Query Params",
        content: buildRequestQueryParams(),
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
