/** 流量日志详情（Drawer 展示，暂为 mock 结构） */
export type TrafficLogDetail = {
  accessTime: string;
  traffic: string;
  logSource: string;
  appName: string;
  userVisitAddress: string;
  path: string;
  visitDomain: string;
  deployDomain: string;
  visitAccount: string;
  userName: string;
  srcIp: string;
  srcPort: string;
  srcIpTag?: string;
  protocol: string;
  dstIp: string;
  dstPort: string;
  dstIpTag?: string;
  apiMethod: string;
  apiProtocol: string;
  visitBusiness: string;
  requestSize: string;
  macAddress: string;
  referer: string;
  xffIp: string;
  requestDataTag: string;
  identifiedFile: string;
  responseStatus: string;
  responseSize: string;
  responseDataTag: string;
  contentType: string;
  responseTime: string;
};

export type TrafficLogDetailField = {
  label: string;
  value: string;
  hint?: string;
};

export type TrafficLogDetailSection = {
  title: string;
  fields: TrafficLogDetailField[];
};
