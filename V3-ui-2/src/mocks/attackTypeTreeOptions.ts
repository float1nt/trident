export type MockAttackTypeTreeNode = {
  searchLabel: string;
  value: string;
  key: string;
  disabled?: boolean;
  children?: MockAttackTypeTreeNode[];
};

type RiskNameLeaf = {
  title: string;
  value: string;
  disabled?: boolean;
};

function createCategoryNode(
  category: string,
  categoryKey: string,
  risks: RiskNameLeaf[],
  options?: { disabled?: boolean },
): MockAttackTypeTreeNode {
  return {
    searchLabel: category,
    value: categoryKey,
    key: categoryKey,
    disabled: options?.disabled,
    children: risks.map((risk) => ({
      searchLabel: risk.title,
      value: risk.value,
      key: risk.value,
      disabled: risk.disabled,
    })),
  };
}

/** 风险类型树形选项（mock，待后端接口支持层级结构后替换） */
export const MOCK_ATTACK_TYPE_TREE: MockAttackTypeTreeNode[] = [
  createCategoryNode("恶意攻击类", "category_malicious_attack", [
    { title: "恶意程序保活连线", value: "MALICIOUS_PERSISTENCE_CONNECTION" },
    { title: "长静默连接远程受控通信", value: "LONG_SILENT_C2" },
    { title: "P2P 僵尸网络通信", value: "P2P_BOTNET" },
    { title: "加密探测内网端口", value: "ENCRYPTED_INTERNAL_PORT_SCAN" },
    { title: "加密协议暴力破解", value: "ENCRYPTED_BRUTE_FORCE" },
    { title: "密态后门操纵", value: "ENCRYPTED_BACKDOOR", disabled: true },
    { title: "加密自动化漏洞刷网", value: "ENCRYPTED_AUTO_VULN_SCAN" },
    { title: "加密矿池回连", value: "ENCRYPTED_MINING_POOL" },
    { title: "远程命令操控设备", value: "REMOTE_COMMAND_CONTROL" },
    { title: "密态非法多跳代理", value: "ENCRYPTED_ILLEGAL_PROXY" },
    { title: "加密链路漏洞攻击", value: "ENCRYPTED_LINK_EXPLOIT" },
    { title: "分布式密态撞库攻击", value: "DISTRIBUTED_ENCRYPTED_CRED_STUFFING" },
  ]),
  createCategoryNode("数据泄露类", "category_data_leak", [
    { title: "暴力集中式数据外传", value: "BULK_DATA_EXFIL" },
    { title: "分批慢速窃取数据", value: "SLOW_BATCH_DATA_THEFT" },
    { title: "伪装解析通道窃密", value: "DISGUISED_DNS_EXFIL" },
    {
      title: "利用正规云平台泄密",
      value: "CLOUD_PLATFORM_LEAK",
      disabled: true,
    },
    { title: "勒索密钥快速外发数据", value: "RANSOM_KEY_EXFIL" },
    { title: "接口爬取数据并勒索", value: "API_SCRAPE_RANSOM" },
    {
      title: "拟真人上网窃密控端",
      value: "HUMAN_LIKE_EXFIL_C2",
      disabled: true,
    },
  ]),
  createCategoryNode(
    "异常行为类",
    "category_abnormal_behavior",
    [
    { title: "未授权商业 VPN 穿透", value: "UNAUTHORIZED_VPN" },
    { title: "隐蔽对抗型隧道", value: "STEALTH_TUNNEL" },
    { title: "违规使用网络网盘/云存储", value: "UNAUTHORIZED_CLOUD_STORAGE" },
    { title: "非授权加密即时通讯", value: "UNAUTHORIZED_ENCRYPTED_IM" },
    { title: "篡改协议伪装通信", value: "PROTOCOL_SPOOFING" },
    { title: "无限会话复用隧道", value: "INFINITE_SESSION_TUNNEL" },
    ],
    { disabled: true },
  ),
];
