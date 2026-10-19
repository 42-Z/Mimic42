'use client';

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { adminApi } from '@/lib/adminApi';
import { queryKeys } from '@/lib/queryClient';
import { getSupabaseClient } from '@/lib/supabase/client';
import type { ApiError } from '@/types';
import type { AdminIdentity } from '@/types/admin';

interface AuthSnapshot {
  ready: boolean;
  userId: string | null;
  error: unknown | null;
}

export interface AdminAccess {
  userId: string | null;
  isLoading: boolean;
  isAdmin: boolean;
  error: unknown | null;
  retry: () => void;
}

const AdminAccessContext = createContext<AdminAccess | null>(null);

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
  const [auth, setAuth] = useState<AuthSnapshot>({ ready: false, userId: null, error: null });
  const authRef = useRef(auth);
  const userIdRef = useRef<string | null>(null);
  const mountedRef = useRef(false);
  const transitionRef = useRef(0);
  const cleanupQueueRef = useRef<Promise<void>>(Promise.resolve());
  const clearedAdminUsersRef = useRef(new Set<string>());

  const updateAuth = useCallback((value: AuthSnapshot) => {
    authRef.current = value;
    setAuth(value);
  }, []);

  const acceptUserId = useCallback(
    (nextUserId: string | null) => {
      const previousUserId = userIdRef.current;
      if (
        previousUserId === nextUserId &&
        authRef.current.ready &&
        authRef.current.error === null
      ) {
        return;
      }

      userIdRef.current = nextUserId;
      const transition = ++transitionRef.current;
      updateAuth({ ready: false, userId: null, error: null });

      const cleanup = cleanupQueueRef.current.then(async () => {
        if (previousUserId === null) return;
        await clearAdminData(queryClient, previousUserId);
        await queryClient.cancelQueries({ queryKey: queryKeys.identity(previousUserId) });
        queryClient.removeQueries({ queryKey: queryKeys.identity(previousUserId) });
        clearedAdminUsersRef.current.delete(previousUserId);
      });
      cleanupQueueRef.current = cleanup.catch(() => undefined);

      void cleanup
        .then(() => {
          if (
            !mountedRef.current ||
            transitionRef.current !== transition ||
            userIdRef.current !== nextUserId
          ) {
            return;
          }
          updateAuth({ ready: true, userId: nextUserId, error: null });
        })
        .catch((error: unknown) => {
          if (!mountedRef.current || transitionRef.current !== transition) return;
          userIdRef.current = null;
          updateAuth({ ready: true, userId: null, error });
        });
    },
    [queryClient, updateAuth],
  );

  useEffect(() => {
    mountedRef.current = true;
    let active = true;
    let eventSequence = 0;
    let supabase: ReturnType<typeof getSupabaseClient>;

    try {
      supabase = getSupabaseClient();
    } catch (error) {
      updateAuth({ ready: true, userId: null, error });
      return () => {
        active = false;
        mountedRef.current = false;
      };
    }

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      eventSequence += 1;
      acceptUserId(session?.user.id ?? null);
    });
    const initialEventSequence = eventSequence;

    void supabase.auth
      .getSession()
      .then(({ data, error }) => {
        if (!active || eventSequence !== initialEventSequence) return;
        if (error) {
          updateAuth({ ready: true, userId: null, error });
          return;
        }
        acceptUserId(data.session?.user.id ?? null);
      })
      .catch((error: unknown) => {
        if (!active || eventSequence !== initialEventSequence) return;
        updateAuth({ ready: true, userId: null, error });
      });

    return () => {
      active = false;
      mountedRef.current = false;
      subscription.unsubscribe();
    };
  }, [acceptUserId, updateAuth]);

  const identityQuery = useQuery({
    queryKey: queryKeys.identity(auth.userId ?? 'anonymous'),
    queryFn: ({ signal }) => adminApi.me({ signal }),
    enabled: auth.ready && auth.userId !== null,
    staleTime: 0,
    refetchInterval: auth.userId === null ? false : 30_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    retry: retryAdminQuery,
  });

  useEffect(() => {
    const userId = auth.userId;
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
  }, [auth.userId, identityQuery.data, identityQuery.error, queryClient]);

  const access: AdminAccess = {
    userId: auth.ready ? auth.userId : null,
    isLoading:
      !auth.ready ||
      (auth.userId !== null && !identityQuery.isFetchedAfterMount && !identityQuery.isError),
    isAdmin:
      auth.ready &&
      auth.userId !== null &&
      identityQuery.isFetchedAfterMount &&
      !identityQuery.isError &&
      identityQuery.data?.user_id === auth.userId &&
      identityQuery.data.is_admin,
    error: auth.error ?? (identityQuery.isError ? identityQuery.error : null),
    retry: () => {
      if (auth.userId !== null) void identityQuery.refetch();
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
