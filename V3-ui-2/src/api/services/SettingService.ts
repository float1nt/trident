import request, { type ResponseData } from "@/utils/request";
import type { IpRangeItem } from "@/components/IpRangeFormList";
import {
  MOCK_COLLECTION_SETTINGS,
  MOCK_PROTOCOL_OPTIONS,
} from "@/mock/collectionSettings";

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

function useMockOnFailure<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  return fn().catch((error) => {
    if (import.meta.env.DEV) {
      console.warn("[SettingService] 使用 mock 数据:", error);
    }
    return fallback;
  });
}

export class SettingService {
  static async getSettings(): Promise<CollectionSettings> {
    return useMockOnFailure(async () => {
      const res = (await request({
        url: SETTINGS_URL,
        method: "get",
      })) as ResponseData<CollectionSettings>;
      return res.data ?? MOCK_COLLECTION_SETTINGS;
    }, MOCK_COLLECTION_SETTINGS);
  }

  static async saveSettings(
    data: CollectionSettings,
  ): Promise<CollectionSettings> {
    return useMockOnFailure(async () => {
      const res = (await request({
        url: SETTINGS_URL,
        method: "put",
        data,
      })) as ResponseData<CollectionSettings>;
      return res.data ?? data;
    }, data);
  }

  static async getProtocols(): Promise<ProtocolOption[]> {
    return useMockOnFailure(async () => {
      const res = (await request({
        url: PROTOCOLS_URL,
        method: "get",
      })) as ResponseData<ProtocolOption[]>;
      return res.data ?? MOCK_PROTOCOL_OPTIONS;
    }, MOCK_PROTOCOL_OPTIONS);
  }
}

export const getCollectionSettings = (): Promise<CollectionSettings> =>
  SettingService.getSettings();

export const saveCollectionSettings = (
  data: CollectionSettings,
): Promise<CollectionSettings> => SettingService.saveSettings(data);

export const getCollectionProtocols = (): Promise<ProtocolOption[]> =>
  SettingService.getProtocols();
