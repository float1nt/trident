import type { RiskItem } from "@/api/types";

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
      const keyword = (params.name ?? "").trim().toLowerCase();
      let filtered = mockRisks;
      if (keyword) {
        filtered = mockRisks.filter((r) =>
          r.name.toLowerCase().includes(keyword)
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

/** @deprecated 使用 getMockRiskById */
export function getMockTaskById(id: number): RiskItem | undefined {
  return getMockRiskById(id);
}
