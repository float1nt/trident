import type { RiskTrafficLogItem } from "@/api/services/RiskService";
import type {
  TrafficLogDetail,
  TrafficLogDetailSection,
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
    {
      title: "基础信息",
      fields: [
        { label: "访问时间", value: detail.accessTime },
        { label: "流量", value: detail.traffic },
        { label: "日志来源", value: detail.logSource },
        { label: "应用名称", value: detail.appName },
        { label: "用户访问地址", value: detail.userVisitAddress },
        { label: "路径", value: detail.path },
        { label: "访问域", value: detail.visitDomain },
        { label: "部署域", value: detail.deployDomain },
        {
          label: "访问账号",
          value: detail.visitAccount,
          hint: "暂无账号识别结果",
        },
        {
          label: "用户名称",
          value: detail.userName,
          hint: "暂无用户识别结果",
        },
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
    {
      title: "请求信息",
      fields: [
        { label: "API请求方法", value: detail.apiMethod },
        { label: "API协议", value: detail.apiProtocol },
        { label: "访问业务", value: detail.visitBusiness },
        { label: "请求大小", value: detail.requestSize },
        {
          label: "MAC地址",
          value: detail.macAddress,
          hint: "暂无 MAC 地址",
        },
        { label: "Referer", value: detail.referer },
        { label: "XFF IP", value: detail.xffIp },
        { label: "请求数据标签", value: detail.requestDataTag },
        { label: "识别文件", value: detail.identifiedFile },
      ],
    },
  ];
}

export function buildInterfaceDetailSections(
  detail: TrafficLogDetail,
): TrafficLogDetailSection[] {
  return [
    {
      title: "响应信息",
      fields: [
        { label: "响应状态", value: detail.responseStatus },
        { label: "响应大小", value: detail.responseSize },
        { label: "响应数据标签", value: detail.responseDataTag },
        { label: "Content-Type", value: detail.contentType },
        { label: "响应耗时", value: detail.responseTime },
      ],
    },
    {
      title: "接口路径",
      fields: [
        { label: "请求路径", value: detail.path },
        { label: "请求方法", value: detail.apiMethod },
        { label: "API协议", value: detail.apiProtocol },
      ],
    },
  ];
}
