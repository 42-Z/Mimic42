import { apiClient } from '@/lib/api';
import type {
  AdminAgentProxy,
  AdminIdentity,
  AdminPage,
  AdminPresetDetail,
  AdminPresetKind,
  AdminPresetSummary,
  AdminProxyCheckResult,
  AdminProxyDetail,
  AdminProxyInput,
  AdminProxySummary,
  AdminStatistics,
  AdminUserDetail,
  AdminUserSummary,
  CreateAdminPreset,
  PublicTelegramSettings,
  SaveTelegramSettings,
  UpdateAdminPreset,
  UpdateAdminProxy,
} from '@/types/admin';

export interface AdminReadOptions {
  signal?: AbortSignal;
}

export const adminApi = {
  me: (options: AdminReadOptions = {}) =>
    apiClient.get<AdminIdentity>('/me', { signal: options.signal }).then((response) => response.data),

  users: (
    params: { q: string; page: number; page_size?: number },
    options: AdminReadOptions = {},
  ) =>
    apiClient
      .get<AdminPage<AdminUserSummary>>('/admin/users', {
        params: { ...params, page_size: params.page_size ?? 25 },
        signal: options.signal,
      })
      .then((response) => response.data),

  user: (
    userId: string,
    params: { page: number; page_size?: number },
    options: AdminReadOptions = {},
  ) =>
    apiClient
      .get<AdminUserDetail>(`/admin/users/${userId}`, {
        params: { ...params, page_size: params.page_size ?? 25 },
        signal: options.signal,
      })
      .then((response) => response.data),

  presets: (
    params: { q: string; kind: AdminPresetKind; page: number; page_size?: number },
    options: AdminReadOptions = {},
  ) =>
    apiClient
      .get<AdminPage<AdminPresetSummary>>('/admin/presets', {
        params: { ...params, page_size: params.page_size ?? 25 },
        signal: options.signal,
      })
      .then((response) => response.data),

  preset: (presetId: string, options: AdminReadOptions = {}) =>
    apiClient
      .get<AdminPresetDetail>(`/admin/presets/${presetId}`, { signal: options.signal })
      .then((response) => response.data),

  createPreset: (values: CreateAdminPreset) =>
    apiClient.post<AdminPresetDetail>('/admin/presets', values).then((response) => response.data),

  updatePreset: (presetId: string, values: UpdateAdminPreset) =>
    apiClient
      .patch<AdminPresetDetail>(`/admin/presets/${presetId}`, values)
      .then((response) => response.data),

  setPresetVisibility: (presetId: string, is_active: boolean) =>
    apiClient
      .patch<AdminPresetDetail>(`/admin/presets/${presetId}/visibility`, { is_active })
      .then((response) => response.data),

  telegramSettings: (options: AdminReadOptions = {}) =>
    apiClient
      .get<PublicTelegramSettings>('/admin/telegram-settings', { signal: options.signal })
      .then((response) => response.data),

  saveTelegramSettings: (values: SaveTelegramSettings) =>
    apiClient
      .put<PublicTelegramSettings>('/admin/telegram-settings', values)
      .then((response) => response.data),

  proxies: (params: { page: number; page_size?: number }, options: AdminReadOptions = {}) =>
    apiClient
      .get<AdminPage<AdminProxySummary>>('/admin/proxies', {
        params: { ...params, page_size: params.page_size ?? 25 },
        signal: options.signal,
      })
      .then((response) => response.data),

  proxyOptions: (options: AdminReadOptions = {}) =>
    apiClient
      .get<AdminAgentProxy[]>('/admin/proxies/options', { signal: options.signal })
      .then((response) => response.data),

  createProxy: (values: AdminProxyInput) =>
    apiClient.post<AdminProxyDetail>('/admin/proxies', values).then((response) => response.data),

  updateProxy: (proxyId: string, values: UpdateAdminProxy) =>
    apiClient
      .patch<AdminProxyDetail>(`/admin/proxies/${proxyId}`, values)
      .then((response) => response.data),

  deleteProxy: (proxyId: string) => apiClient.delete(`/admin/proxies/${proxyId}`),

  checkProxy: (proxyId: string) =>
    apiClient
      .post<AdminProxyCheckResult>(`/admin/proxies/${proxyId}/check`)
      .then((response) => response.data),

  assignAgentProxy: (agentId: string, proxyId: string | null) =>
    apiClient
      .put<AdminAgentProxy | null>(`/admin/agents/${agentId}/proxy`, { proxy_id: proxyId })
      .then((response) => response.data),

  statistics: (days: 7 | 30, options: AdminReadOptions = {}) =>
    apiClient
      .get<AdminStatistics>('/admin/statistics', {
        params: { days },
        signal: options.signal,
      })
      .then((response) => response.data),
};
