import {
  mockGetCollectionProtocols,
  mockGetCollectionSettings,
  mockSaveCollectionSettings,
} from "@/mock/collectionSettings";
import type {
  CollectionSettings,
  ProtocolOption,
} from "@/types/collectionSettings";

export type { CollectionSettings, ProtocolOption };

/**
 * 采集配置暂用前端 Mock。
 * 后续由 streamtrident_services/trident-api（默认 8090）提供接口时，
 * 改回 request 并走 Vite `/api` 代理即可。
 */
export class SettingService {
  static getSettings(): Promise<CollectionSettings> {
    return mockGetCollectionSettings();
  }

  static saveSettings(data: CollectionSettings): Promise<CollectionSettings> {
    return mockSaveCollectionSettings(data);
  }

  static getProtocols(): Promise<ProtocolOption[]> {
    return mockGetCollectionProtocols();
  }
}

export const getCollectionSettings = (): Promise<CollectionSettings> =>
  SettingService.getSettings();

export const saveCollectionSettings = (
  data: CollectionSettings,
): Promise<CollectionSettings> => SettingService.saveSettings(data);

export const getCollectionProtocols = (): Promise<ProtocolOption[]> =>
  SettingService.getProtocols();
