import request, { type ResponseData } from "@/utils/request";
import type { IpRangeItem } from "@/components/IpRangeFormList";

export interface CollectionSettings {
  maxTrafficLimitGbps: number;
  sourceIpRanges: IpRangeItem[];
  destIpRanges: IpRangeItem[];
  protocols: string[];
}

export interface ProtocolOption {
  value: string;
  label: string;
}

const SETTINGS_URL = "/collection/settings";
const PROTOCOLS_URL = "/collection/protocols";

export class SettingService {
  static async getSettings(): Promise<CollectionSettings> {
    const res = (await request({
      url: SETTINGS_URL,
      method: "get",
    })) as ResponseData<CollectionSettings>;
    if (!res.data) {
      throw new Error(res.message || "获取采集配置失败");
    }
    return res.data;
  }

  static async saveSettings(
    data: CollectionSettings,
  ): Promise<CollectionSettings> {
    const res = (await request({
      url: SETTINGS_URL,
      method: "put",
      data,
    })) as ResponseData<CollectionSettings>;
    return res.data ?? data;
  }

  static async getProtocols(): Promise<ProtocolOption[]> {
    const res = (await request({
      url: PROTOCOLS_URL,
      method: "get",
    })) as ResponseData<ProtocolOption[]>;
    if (!res.data) {
      throw new Error(res.message || "获取协议列表失败");
    }
    return res.data;
  }
}

export const getCollectionSettings = (): Promise<CollectionSettings> =>
  SettingService.getSettings();

export const saveCollectionSettings = (
  data: CollectionSettings,
): Promise<CollectionSettings> => SettingService.saveSettings(data);

export const getCollectionProtocols = (): Promise<ProtocolOption[]> =>
  SettingService.getProtocols();
