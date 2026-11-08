import { QueryClient } from '@tanstack/react-query';

// ── Query keys — centralized for predictable cache invalidation ───────────────
export const queryKeys = {
  // Admin identity and data are scoped to the authenticated user.
  identity: (userId: string) => ['identity', userId] as const,
  admin: {
    all: ['admin'] as const,
    scope: (userId: string) => ['admin', userId] as const,
    users: (userId: string, q: string, page: number, pageSize: number) =>
      ['admin', userId, 'users', { q, page, pageSize }] as const,
    user: (userId: string, targetId: string, page: number, pageSize: number) =>
      ['admin', userId, 'user', targetId, { page, pageSize }] as const,
    presets: (userId: string, q: string, kind: string, page: number, pageSize: number) =>
      ['admin', userId, 'presets', { q, kind, page, pageSize }] as const,
    preset: (userId: string, presetId: string) => ['admin', userId, 'preset', presetId] as const,
    telegram: (userId: string) => ['admin', userId, 'telegram'] as const,
    proxies: (userId: string, page: number, pageSize: number) =>
      ['admin', userId, 'proxies', { page, pageSize }] as const,
    proxyOptions: (userId: string) => ['admin', userId, 'proxy-options'] as const,
    statistics: (userId: string, days: 7 | 30) => ['admin', userId, 'statistics', days] as const,
  },

  forUser: privateQueryKeys,
} as const;

function privateQueryKeys(userId: string | null) {
  const queryKeys = {
    agents: {
      all: ['account', userId, 'agents'] as const,
      lists: () => [...queryKeys.agents.all, 'list'] as const,
      list: () => [...queryKeys.agents.lists()] as const,
      details: () => [...queryKeys.agents.all, 'detail'] as const,
      detail: (id: string) => [...queryKeys.agents.details(), id] as const,
      chats: (id: string) => [...queryKeys.agents.all, 'chats', id] as const,
      detailsAll: (agentIds: string[]) =>
        [...queryKeys.agents.all, 'details-all', [...agentIds].sort()] as const,
    },
    conversation: {
      all: ['account', userId, 'conversation'] as const,
      byAgent: (agentId: string) => [...queryKeys.conversation.all, agentId] as const,
    },
    media: {
      all: ['account', userId, 'media'] as const,
      link: (agentId: string, storagePath: string) =>
        [...queryKeys.media.all, agentId, storagePath] as const,
    },
    onboarding: {
      all: ['account', userId, 'onboarding'] as const,
      session: () => [...queryKeys.onboarding.all, 'session'] as const,
    },
    telegram: {
      all: ['account', userId, 'telegram'] as const,
      byAgent: (agentId: string) => [...queryKeys.telegram.all, agentId] as const,
      password: (agentId: string) => [...queryKeys.telegram.all, agentId, 'password'] as const,
    },
    threads: {
      all: ['account', userId, 'threads'] as const,
      byAgent: (agentId: string) => [...queryKeys.threads.all, agentId] as const,
    },
    analytics: {
      all: ['account', userId, 'analytics'] as const,
      byAgent: (agentId: string, days: number) =>
        [...queryKeys.analytics.all, agentId, days] as const,
      kpis: (agentId: string) => [...queryKeys.analytics.all, agentId, 'kpis'] as const,
      kpisAll: (agentIds: string[]) =>
        [...queryKeys.analytics.all, { kpisAll: [...agentIds].sort() }] as const,
      usage: (agentId: string) => [...queryKeys.analytics.all, agentId, 'usage'] as const,
    },
    profile: {
      all: ['account', userId, 'profile'] as const,
      current: () => [...queryKeys.profile.all, 'current'] as const,
    },
    presets: {
      all: ['account', userId, 'presets'] as const,
      list: () => [...queryKeys.presets.all, 'list'] as const,
      favorites: () => [...queryKeys.presets.all, 'favorites'] as const,
      authors: () => [...queryKeys.presets.all, 'authors'] as const,
    },
    memories: {
      all: ['account', userId, 'memories'] as const,
      byAgent: (agentId: string) => [...queryKeys.memories.all, agentId] as const,
      byAgentSearch: (agentId: string, query?: string) =>
        [...queryKeys.memories.byAgent(agentId), { query }] as const,
      history: (agentId: string, memoryId: string) =>
        [...queryKeys.memories.byAgent(agentId), 'history', memoryId] as const,
    },
  } as const;
  return queryKeys;
}

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Data is considered fresh for 30 seconds
        staleTime: 30_000,
        // Keep inactive data in cache for 5 minutes
        gcTime: 5 * 60 * 1000,
        // Retry failed requests twice
        retry: 2,
        // Retry after 1s, then 2s
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10_000),
        // Refetch on window focus for live data
        refetchOnWindowFocus: true,
        // Don't refetch on reconnect by default (we have realtime)
        refetchOnReconnect: false,
      },
      mutations: {
        // Don't retry mutations — user should retry manually
        retry: 0,
      },
    },
  });
}

// Historical data (messages, events) stays fresh longer
export const HISTORICAL_STALE_TIME = 5 * 60 * 1000;

// Status data refreshes quickly
export const STATUS_STALE_TIME = 10_000;
