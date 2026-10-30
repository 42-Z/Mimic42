'use client';

import { useCallback, useRef } from 'react';
import { useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { adminApi } from '@/lib/adminApi';
import { queryKeys } from '@/lib/queryClient';
import { clearAdminData, retryAdminQuery, useAdminAccess } from '@/hooks/useAdminAccess';
import type { ApiError } from '@/types';
import type {
  AdminPresetKind,
  AdminProxyImportInput,
  AdminProxyInput,
  CreateAdminPreset,
  SaveTelegramSettings,
  UpdateAdminPreset,
  UpdateAdminProxy,
} from '@/types/admin';

function errorStatus(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null || !('status' in error)) return undefined;
  const status = (error as Partial<ApiError>).status;
  return typeof status === 'number' ? status : undefined;
}

function useAdminRead<T>(
  queryKey: QueryKey,
  userId: string | null,
  isAdmin: boolean,
  queryFn: (signal: AbortSignal) => Promise<T>,
  refetchInterval?: number | false,
  active = true,
) {
  const queryClient = useQueryClient();

  return useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      if (userId === null) throw new Error('Admin query started without a user');
      try {
        return await queryFn(signal);
      } catch (error) {
        if ([401, 403].includes(errorStatus(error) ?? -1)) {
          queryClient.setQueryData(queryKeys.identity(userId), {
            user_id: userId,
            is_admin: false,
          });
          void clearAdminData(queryClient, userId).catch(() => undefined);
        }
        throw error;
      }
    },
    enabled: active && userId !== null && isAdmin,
    retry: retryAdminQuery,
    refetchInterval,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
}

export function useAdminUsers(q: string, page: number, pageSize = 25) {
  const { userId, isAdmin } = useAdminAccess();
  return useAdminRead(
    queryKeys.admin.users(userId ?? '', q, page, pageSize),
    userId,
    isAdmin,
    (signal) => adminApi.users({ q, page, page_size: pageSize }, { signal }),
  );
}

export function useAdminUser(userId: string, page: number, pageSize = 25) {
  const access = useAdminAccess();
  const targetUserId = userId.trim();
  return useAdminRead(
    queryKeys.admin.user(access.userId ?? '', targetUserId, page, pageSize),
    access.userId,
    access.isAdmin && targetUserId.length > 0,
    (signal) => adminApi.user(targetUserId, { page, page_size: pageSize }, { signal }),
  );
}

export function useAdminPresets(
  q: string,
  kind: AdminPresetKind,
  page: number,
  pageSize = 25,
) {
  const { userId, isAdmin } = useAdminAccess();
  return useAdminRead(
    queryKeys.admin.presets(userId ?? '', q, kind, page, pageSize),
    userId,
    isAdmin,
    (signal) => adminApi.presets({ q, kind, page, page_size: pageSize }, { signal }),
  );
}

export function useAdminPreset(presetId: string) {
  const { userId, isAdmin } = useAdminAccess();
  const targetPresetId = presetId.trim();
  return useAdminRead(
    queryKeys.admin.preset(userId ?? '', targetPresetId),
    userId,
    isAdmin && targetPresetId.length > 0,
    (signal) => adminApi.preset(targetPresetId, { signal }),
  );
}

export function useAdminTelegramSettings() {
  const { userId, isAdmin } = useAdminAccess();
  return useAdminRead(
    queryKeys.admin.telegram(userId ?? ''),
    userId,
    isAdmin,
    (signal) => adminApi.telegramSettings({ signal }),
  );
}

export function useAdminProxies(page: number, pageSize = 25) {
  const { userId, isAdmin } = useAdminAccess();
  return useAdminRead(
    queryKeys.admin.proxies(userId ?? '', page, pageSize),
    userId,
    isAdmin,
    (signal) => adminApi.proxies({ page, page_size: pageSize }, { signal }),
  );
}

export function useAdminProxyOptions(active = true) {
  const { userId, isAdmin } = useAdminAccess();
  return useAdminRead(
    queryKeys.admin.proxyOptions(userId ?? ''),
    userId,
    isAdmin,
    (signal) => adminApi.proxyOptions({ signal }),
    undefined,
    active,
  );
}

export function useAdminStatistics(days: 7 | 30) {
  const { userId, isAdmin } = useAdminAccess();
  return useAdminRead(
    queryKeys.admin.statistics(userId ?? '', days),
    userId,
    isAdmin,
    (signal) => adminApi.statistics(days, { signal }),
    60_000,
  );
}

export function useAdminActions() {
  const { userId, isAdmin } = useAdminAccess();
  const queryClient = useQueryClient();
  const currentAccess = useRef({ userId, isAdmin });
  currentAccess.current = { userId, isAdmin };

  const execute = useCallback(
    async <Result,>(
      operation: () => Promise<Result>,
      afterSuccess?: (initiatingUserId: string) => Promise<void>,
    ): Promise<Result> => {
      const initiatingUserId = userId;
      if (initiatingUserId === null || !isAdmin) {
        throw new Error('Admin access is not confirmed');
      }

      try {
        const result = await operation();
        if (
          currentAccess.current.userId !== initiatingUserId ||
          !currentAccess.current.isAdmin
        ) {
          throw new Error('Admin access changed while the request was in flight');
        }
        if (afterSuccess) {
          await afterSuccess(initiatingUserId);
          if (
            currentAccess.current.userId !== initiatingUserId ||
            !currentAccess.current.isAdmin
          ) {
            throw new Error('Admin access changed while refreshing cached data');
          }
        }
        return result;
      } catch (error) {
        if ([401, 403].includes(errorStatus(error) ?? -1)) {
          queryClient.setQueryData(queryKeys.identity(initiatingUserId), {
            user_id: initiatingUserId,
            is_admin: false,
          });
          void clearAdminData(queryClient, initiatingUserId).catch(() => undefined);
        }
        throw error;
      }
    },
    [isAdmin, queryClient, userId],
  );

  return {
    createPreset: (values: CreateAdminPreset) =>
      execute(() => adminApi.createPreset(values), async (ownerId) => {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.admin.scope(ownerId) }),
          queryClient.invalidateQueries({ queryKey: queryKeys.presets.all }),
        ]);
      }),
    updatePreset: (presetId: string, values: UpdateAdminPreset) =>
      execute(() => adminApi.updatePreset(presetId, values), async (ownerId) => {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.admin.scope(ownerId) }),
          queryClient.invalidateQueries({ queryKey: queryKeys.presets.all }),
        ]);
      }),
    setPresetVisibility: (presetId: string, isActive: boolean) =>
      execute(() => adminApi.setPresetVisibility(presetId, isActive), async (ownerId) => {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.admin.scope(ownerId) }),
          queryClient.invalidateQueries({ queryKey: queryKeys.presets.all }),
        ]);
      }),
    saveTelegramSettings: (values: SaveTelegramSettings) =>
      execute(() => adminApi.saveTelegramSettings(values), async (ownerId) => {
        void queryClient
          .invalidateQueries({ queryKey: queryKeys.admin.telegram(ownerId) })
          .catch(() => undefined);
      }),
    createProxy: (values: AdminProxyInput) =>
      execute(() => adminApi.createProxy(values), async (ownerId) => {
        await queryClient.invalidateQueries({ queryKey: queryKeys.admin.scope(ownerId) });
      }),
    importProxies: (values: AdminProxyImportInput) =>
      execute(() => adminApi.importProxies(values), async (ownerId) => {
        await queryClient.invalidateQueries({ queryKey: queryKeys.admin.scope(ownerId) });
      }),
    updateProxy: (proxyId: string, values: UpdateAdminProxy) =>
      execute(() => adminApi.updateProxy(proxyId, values), async (ownerId) => {
        await queryClient.invalidateQueries({ queryKey: queryKeys.admin.scope(ownerId) });
      }),
    deleteProxy: (proxyId: string) =>
      execute(() => adminApi.deleteProxy(proxyId), async (ownerId) => {
        await queryClient.invalidateQueries({ queryKey: queryKeys.admin.scope(ownerId) });
      }),
    checkProxy: (proxyId: string) => execute(() => adminApi.checkProxy(proxyId)),
    assignAgentProxy: (agentId: string, proxyId: string | null) =>
      execute(() => adminApi.assignAgentProxy(agentId, proxyId), async (ownerId) => {
        await queryClient.invalidateQueries({ queryKey: queryKeys.admin.scope(ownerId) });
      }),
  };
}
