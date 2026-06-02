export type AttackTypeCatalogNode = {
  searchLabel: string;
  value: string;
  key: string;
  children?: AttackTypeCatalogNode[];
};

type RiskNameLeaf = {
  title: string;
  value: string;
};

function createCategoryNode(
  category: string,
  categoryKey: string,
  risks: RiskNameLeaf[],
): AttackTypeCatalogNode {
  return {
    searchLabel: category,
    value: categoryKey,
    key: categoryKey,
    children: risks.map((risk) => ({
      searchLabel: risk.title,
      value: risk.value,
      key: risk.value,
    })),
  };
}

/** 完整风险类型目录。是否可选和学习器数量由 /risk/attack-types 实时结果决定。 */
export const ATTACK_TYPE_CATALOG: AttackTypeCatalogNode[] = [
  createCategoryNode("恶意攻击类", "category_malicious_attack", [
    { title: "未命名攻击", value: "UNKNOWN_SUSPECTED" },
    { title: "恶意程序保活连线", value: "C2_HEARTBEAT_CONNECTION" },
    { title: "长静默连接远程受控通信", value: "C2_LONG_SILENT_CONTROL" },
    { title: "P2P 僵尸网络通信", value: "P2P_BOTNET_COMMUNICATION" },
    { title: "加密探测内网端口", value: "ENCRYPTED_INTERNAL_SCAN" },
    { title: "加密协议暴力破解", value: "ENCRYPTED_PROTOCOL_BRUTE_FORCE" },
    { title: "密态后门操纵", value: "ENCRYPTED_BACKDOOR" },
    { title: "加密自动化漏洞刷网", value: "ENCRYPTED_AUTOMATED_VULNERABILITY_SWEEP" },
    { title: "加密矿池回连", value: "CRYPTOMINING_POOL_CALLBACK" },
    { title: "远程命令操控设备", value: "INTERACTIVE_REVERSE_SHELL" },
    { title: "密态非法多跳代理", value: "ENCRYPTED_MULTI_HOP_PROXY" },
    { title: "加密链路漏洞攻击", value: "ENCRYPTED_LINK_EXPLOIT" },
    { title: "分布式密态撞库攻击", value: "DISTRIBUTED_ENCRYPTED_CRED_STUFFING" },
  ]),
  createCategoryNode("数据泄露类", "category_data_leak", [
    { title: "暴力集中式数据外传", value: "CENTRALIZED_DATA_EXFILTRATION" },
    { title: "分批慢速窃取数据", value: "BATCHED_SLOW_DATA_EXFILTRATION" },
    { title: "伪装解析通道窃密", value: "DISGUISED_DNS_EXFIL" },
    { title: "利用正规云平台泄密", value: "CLOUD_PLATFORM_LEAK" },
    { title: "勒索密钥快速外发数据", value: "RANSOMWARE_KEY_EXFILTRATION" },
    { title: "接口爬取数据并勒索", value: "API_RESOURCE_EXTORTION" },
    { title: "拟真人上网窃密控端", value: "HUMAN_LIKE_EXFIL_C2" },
  ]),
  createCategoryNode("异常行为类", "category_abnormal_behavior", [
    { title: "未授权商业 VPN 穿透", value: "UNAUTHORIZED_VPN" },
    { title: "隐蔽对抗型隧道", value: "STEALTH_TUNNEL" },
    { title: "违规使用网络网盘/云存储", value: "UNAUTHORIZED_CLOUD_STORAGE" },
    { title: "非授权加密即时通讯", value: "UNAUTHORIZED_ENCRYPTED_IM" },
    { title: "篡改协议伪装通信", value: "PROTOCOL_SPOOFING" },
    { title: "无限会话复用隧道", value: "INFINITE_SESSION_TUNNEL" },
  ]),
];
