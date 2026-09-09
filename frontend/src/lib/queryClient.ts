import { QueryClient } from '@tanstack/react-query';

// ── Query keys — centralized for predictable cache invalidation ───────────────
export const queryKeys = {
  // Agents
  agents: {
    all: ['agents'] as const,
    lists: () => [...queryKeys.agents.all, 'list'] as const,
    list: () => [...queryKeys.agents.lists()] as const,
    details: () => [...queryKeys.agents.all, 'detail'] as const,
    detail: (id: string) => [...queryKeys.agents.details(), id] as const,
    detailsAll: (agentIds: string[]) =>
      [...queryKeys.agents.all, 'details-all', [...agentIds].sort()] as const,
  },

  // Agent messages
  messages: {
    all: ['messages'] as const,
    byAgent: (agentId: string) => [...queryKeys.messages.all, agentId] as const,
    byAgentPaged: (agentId: string, limit: number) =>
      [...queryKeys.messages.byAgent(agentId), { limit }] as const,
  },

  // Agent events/actions
  actions: {
    all: ['actions'] as const,
    byAgent: (agentId: string) => [...queryKeys.actions.all, agentId] as const,
    byAgentPaged: (agentId: string, limit: number) =>
      [...queryKeys.actions.byAgent(agentId), { limit }] as const,
  },

  // Conversation turns (grouped messages)
  conversation: {
    all: ['conversation'] as const,
    byAgent: (agentId: string) => [...queryKeys.conversation.all, agentId] as const,
  },

  // Onboarding session
  onboarding: {
    all: ['onboarding'] as const,
    session: () => [...queryKeys.onboarding.all, 'session'] as const,
  },

  // Telegram session
  telegram: {
    all: ['telegram'] as const,
    byAgent: (agentId: string) => [...queryKeys.telegram.all, agentId] as const,
  },

  // Message threads
  threads: {
    all: ['threads'] as const,
    byAgent: (agentId: string) => [...queryKeys.threads.all, agentId] as const,
  },

  // Analytics
  analytics: {
    all: ['analytics'] as const,
    byAgent: (agentId: string, days: number) =>
      [...queryKeys.analytics.all, agentId, days] as const,
    kpis: (agentId: string) => [...queryKeys.analytics.all, agentId, 'kpis'] as const,
    kpisAll: (agentIds: string[]) =>
      [...queryKeys.analytics.all, { kpisAll: [...agentIds].sort() }] as const,
  },

  // Profile
  profile: {
    all: ['profile'] as const,
    current: () => [...queryKeys.profile.all, 'current'] as const,
  },

  // Memories
  memories: {
    all: ['memories'] as const,
    byAgent: (agentId: string) => [...queryKeys.memories.all, agentId] as const,
    byAgentSearch: (agentId: string, query?: string) =>
      [...queryKeys.memories.byAgent(agentId), { query }] as const,
    history: (agentId: string, memoryId: string) =>
      [...queryKeys.memories.byAgent(agentId), 'history', memoryId] as const,
  },
} as const;

// ── Create the global QueryClient ─────────────────────────────────────────────
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
