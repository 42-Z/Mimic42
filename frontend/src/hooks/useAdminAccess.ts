'use client';

import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useRef,
  type ReactNode,
} from 'react';
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { adminApi } from '@/lib/adminApi';
import { queryKeys } from '@/lib/queryClient';
import { useAccount } from '@/hooks/useAccount';
import type { ApiError } from '@/types';
import type { AdminIdentity } from '@/types/admin';

export interface AdminAccess {
  userId: string | null;
  isLoading: boolean;
  isAdmin: boolean;
  isDenied: boolean;
  error: unknown | null;
  retry: () => void;
}

export const AdminAccessContext = createContext<AdminAccess | null>(null);

function errorStatus(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null || !('status' in error)) return undefined;
  const status = (error as Partial<ApiError>).status;
  return typeof status === 'number' ? status : undefined;
}

export function retryAdminQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= 1) return false;
  const status = errorStatus(error);
  return status === 0 || status === 503;
}

export async function clearAdminData(queryClient: QueryClient, userId: string): Promise<void> {
  const queryKey = queryKeys.admin.scope(userId);
  try {
    await queryClient.cancelQueries({ queryKey });
  } finally {
    queryClient.removeQueries({ queryKey });
  }
}

export async function revokeAdminAccess(
  queryClient: QueryClient,
  userId: string,
): Promise<void> {
  queryClient.setQueryData<AdminIdentity>(queryKeys.identity(userId), {
    user_id: userId,
    is_admin: false,
  });
  await clearAdminData(queryClient, userId);
}

export function AdminAccessProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const account = useAccount();
  const userId = account?.userId ?? null;
  const clearedAdminUsersRef = useRef(new Set<string>());

  const identityQuery = useQuery({
    queryKey: queryKeys.identity(userId ?? 'anonymous'),
    queryFn: ({ signal }) => adminApi.me({ signal }),
    enabled: userId !== null,
    staleTime: 0,
    refetchInterval: userId === null ? false : 30_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    retry: retryAdminQuery,
  });

  useEffect(() => {
    if (userId === null) return;

    const identity = identityQuery.data;
    const status = errorStatus(identityQuery.error);
    if (status === 401 || status === 403) {
      if (clearedAdminUsersRef.current.has(userId)) return;
      clearedAdminUsersRef.current.add(userId);
      queryClient.setQueryData<AdminIdentity>(queryKeys.identity(userId), {
        user_id: userId,
        is_admin: false,
      });
      void clearAdminData(queryClient, userId).catch(() => undefined);
      return;
    }

    if (identity?.user_id === userId && identity.is_admin) {
      clearedAdminUsersRef.current.delete(userId);
      return;
    }

    if (identity?.user_id === userId && !identity.is_admin) {
      if (clearedAdminUsersRef.current.has(userId)) return;
      clearedAdminUsersRef.current.add(userId);
      void clearAdminData(queryClient, userId).catch(() => undefined);
    }
  }, [userId, identityQuery.data, identityQuery.error, queryClient]);

  const access: AdminAccess = {
    userId,
    isLoading:
      userId !== null && !identityQuery.isFetchedAfterMount && !identityQuery.isError,
    isAdmin:
      userId !== null &&
      identityQuery.isFetchedAfterMount &&
      !identityQuery.isError &&
      identityQuery.data?.user_id === userId &&
      identityQuery.data.is_admin,
    isDenied:
      userId === null ||
        (userId !== null &&
          ((identityQuery.isFetchedAfterMount &&
            identityQuery.data?.user_id === userId &&
            !identityQuery.data.is_admin) ||
            errorStatus(identityQuery.error) === 403)),
    error: identityQuery.isError ? identityQuery.error : null,
    retry: () => {
      if (userId !== null) void identityQuery.refetch();
    },
  };

  return createElement(AdminAccessContext.Provider, { value: access }, children);
}

export function useAdminAccess(): AdminAccess {
  const access = useContext(AdminAccessContext);
  if (access === null) {
    throw new Error('useAdminAccess must be used inside AdminAccessProvider');
  }
  return access;
}
