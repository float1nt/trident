import { get, post, put } from "@/utils/request";
import type {
  CollectionApplyResult,
  CollectionAgentStatusResponse,
  CollectionSettings,
  CollectionSettingsSaveResult,
  CollectionSettingsState,
  ProtocolOption,
} from "@/types/collectionSettings";

export type {
  CollectionApplyResult,
  CollectionAgentStatusResponse,
  CollectionSettings,
  CollectionSettingsSaveResult,
  CollectionSettingsState,
  ProtocolOption,
};

function isSettingsState(
  data: CollectionSettings | CollectionSettingsState,
): data is CollectionSettingsState {
  return "settings" in data;
}

export class SettingService {
  static async getSettings(): Promise<CollectionSettingsState> {
    const res = await get<CollectionSettings | CollectionSettingsState>("/collection/settings");
    const data = res.data!;
    return isSettingsState(data)
      ? data
      : { settings: data, revision: 1, lastApply: null };
  }

  static async saveSettings(data: CollectionSettings): Promise<CollectionSettingsSaveResult> {
    const res = await put<CollectionSettings | CollectionSettingsSaveResult>("/collection/settings", data);
    const saved = res.data!;
    return "apply" in saved
      ? saved
      : { settings: saved, revision: 1, apply: { applied: true, agents: [] } };
  }

  static async getProtocols(): Promise<ProtocolOption[]> {
    const res = await get<ProtocolOption[]>("/collection/protocols");
    return res.data ?? [];
  }

  static async applySettings(): Promise<CollectionApplyResult> {
    const res = await post<CollectionApplyResult>("/collection/settings/apply");
    return res.data!;
  }

  static async getAgentStatus(): Promise<CollectionAgentStatusResponse> {
    const res = await get<CollectionAgentStatusResponse>("/collection/agents/status");
    return res.data!;
  }

  static async refreshAgentStatus(): Promise<CollectionAgentStatusResponse> {
    const res = await post<CollectionAgentStatusResponse>("/collection/agents/refresh");
    return res.data!;
  }
}

export const getCollectionSettings = (): Promise<CollectionSettingsState> =>
  SettingService.getSettings();

export const saveCollectionSettings = (
  data: CollectionSettings,
): Promise<CollectionSettingsSaveResult> => SettingService.saveSettings(data);

export const getCollectionProtocols = (): Promise<ProtocolOption[]> =>
  SettingService.getProtocols();

export const applyCollectionSettings = (): Promise<CollectionApplyResult> =>
  SettingService.applySettings();

export const getCollectionAgentStatus = (): Promise<CollectionAgentStatusResponse> =>
  SettingService.getAgentStatus();

export const refreshCollectionAgentStatus = (): Promise<CollectionAgentStatusResponse> =>
  SettingService.refreshAgentStatus();
