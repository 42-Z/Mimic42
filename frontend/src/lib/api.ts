import axios, {
  CanceledError,
  type AxiosError,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios';
import { encodeMediaPath } from '@/lib/mediaPath';
import { getSupabaseClient } from '@/lib/supabase/client';
import type { ApiError, ConversationTurn } from '@/types';

export interface ConversationPage {
  turns: ConversationTurn[];
  next_before: string | null;
  next_before_id: string | null;
}

/** Keyset-курсор ленты: (before, id) — равные timestamp не теряют ходы. */
export interface ConversationCursor {
  before: string;
  id: string;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

export interface ApiAccountScope {
  userId: string | null;
  signal: AbortSignal;
}

declare module 'axios' {
  interface AxiosRequestConfig {
    accountScope?: ApiAccountScope;
  }
}

/**
 * Central Axios instance for all FastAPI requests.
 * Automatically attaches Supabase JWT to every request.
 */
export const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  timeout: 30_000,
  headers: {
    'Content-Type': 'application/json',
  },
});

export function setApiAccountScope(scope: ApiAccountScope | undefined) {
  (apiClient.defaults as typeof apiClient.defaults & { accountScope?: ApiAccountScope }).accountScope = scope;
}

// ── Request interceptor — attach JWT ─────────────────────────────────────────
apiClient.interceptors.request.use(
  async (config: InternalAxiosRequestConfig) => {
    const scope = config.accountScope;
    const assertCurrent = () => {
      if (scope?.signal.aborted || config.signal?.aborted) throw new CanceledError('Account changed');
    };
    assertCurrent();
    const supabase = getSupabaseClient();
    const { data: { session }, error } = await supabase.auth.getSession();
    assertCurrent();
    if (error) throw error;
    if (scope && (session?.user.id ?? null) !== scope.userId) throw new CanceledError('Account changed');
    if (scope) {
      config.signal = config.signal
        ? AbortSignal.any([scope.signal, config.signal as AbortSignal])
        : scope.signal;
    }

    if (session?.access_token) {
      config.headers.Authorization = `Bearer ${session.access_token}`;
    }

    return config;
  },
  (error: unknown) => Promise.reject(error)
);

// ── Response interceptor — normalize errors ───────────────────────────────────
apiClient.interceptors.response.use(
  (response) => {
    if (response.config.accountScope?.signal.aborted) throw new CanceledError('Account changed');
    return response;
  },
  (error: AxiosError) => {
    if (axios.isCancel(error) || error.config?.accountScope?.signal.aborted) {
      return Promise.reject(new CanceledError('Account changed'));
    }
    const status = error.response?.status;
    const detail = (error.response?.data as Record<string, unknown>)?.detail;

    let message = 'Произошла ошибка. Попробуйте снова.';

    switch (status) {
      case 400:
        message = (typeof detail === 'string' ? detail : null) ?? 'Неверный запрос.';
        break;
      case 401:
        message = 'Сессия истекла. Войдите снова.';
        // Redirect to login — only in browser context
        if (typeof window !== 'undefined') {
          window.location.href = '/login';
        }
        break;
      case 403:
        message = 'Нет доступа к этому ресурсу.';
        break;
      case 404:
        message = 'Ресурс не найден.';
        break;
      case 409:
        message = (typeof detail === 'string' && detail) || 'Конфликт: ресурс уже существует.';
        break;
      case 422:
        message = formatValidationError(detail);
        break;
      case 428:
        message = (typeof detail === 'string' && detail) || 'Требуется 2FA пароль.';
        break;
      case 429:
        message =
          (typeof detail === 'string' && detail) ||
          'Слишком много запросов. Подождите немного.';
        break;
      case 500:
        message = 'Внутренняя ошибка сервера.';
        break;
      case 503:
        message = (typeof detail === 'string' && detail) || 'Сервер временно недоступен.';
        break;
      default:
        if (!error.response) {
          message = 'Нет связи с сервером. Проверьте подключение.';
        }
    }

    const normalized: ApiError = {
      status: status ?? 0,
      message,
      detail: detail as string | Record<string, unknown> | undefined,
    };

    return Promise.reject(normalized);
  }
);

function formatValidationError(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const first = detail[0] as Record<string, unknown>;
    if (first?.msg) return String(first.msg);
  }
  return 'Ошибка валидации данных.';
}

// ── Typed API helpers ─────────────────────────────────────────────────────────

import type {
  AgentChat,
  AgentRecord,
  AgentStatus,
  OnboardingTelegramInput,
  OnboardingPublicStatus,
  TelegramCodeInput,
  FinalizeAgentInput,
  TriggerMessageInput,
  TriggerMessageResponse,
  AgentMemory,
  MemoryHistoryItem,
  MediaLink,
  UploadedMedia,
  WarmupState,
  TelegramPasswordInput,
  TelegramPasswordResponse,
  TelegramPasswordState,
  TelegramUsernameInput,
  TelegramUsernameResponse,
} from '@/types';

export const agentsApi = {
  /** GET /api/v1/agents */
  list: (options?: AxiosRequestConfig) =>
    apiClient.get<AgentRecord[]>('/agents', options).then((r) => r.data),

  /** GET /api/v1/agents/:id */
  get: (id: string, options?: AxiosRequestConfig) =>
    apiClient.get<AgentStatus>(`/agents/${id}`, options).then((r) => r.data),

  /** POST /api/v1/agents/:id/start */
  start: (id: string, options?: AxiosRequestConfig) =>
    apiClient.post<void>(`/agents/${id}/start`, undefined, options).then(() => undefined),

  /** POST /api/v1/agents/:id/stop */
  stop: (id: string, options?: AxiosRequestConfig) =>
    apiClient.post<void>(`/agents/${id}/stop`, undefined, options).then(() => undefined),

  /** POST /api/v1/agents/:id/reload — re-applies settings to the runtime */
  reload: (id: string, options?: AxiosRequestConfig) =>
    apiClient.post<void>(`/agents/${id}/reload`, undefined, options).then(() => undefined),

  /** POST /api/v1/agents/:id/telegram/rebind — запросить код входа */
  rebindTelegram: (id: string, options?: AxiosRequestConfig) =>
    apiClient
      .post<OnboardingPublicStatus>(`/agents/${id}/telegram/rebind`, undefined, options)
      .then((r) => r.data),

  /** POST /api/v1/agents/:id/telegram/rebind/confirm — применить новую сессию */
  confirmRebind: (id: string, body: { onboarding_id: string }, options?: AxiosRequestConfig) =>
    apiClient
      .post<AgentStatus>(`/agents/${id}/telegram/rebind/confirm`, body, options)
      .then((r) => r.data),

  /** GET /api/v1/agents/:id/telegram/password — есть ли облачный пароль */
  getTelegramPasswordState: (id: string, options?: AxiosRequestConfig) =>
    apiClient
      .get<TelegramPasswordState>(`/agents/${id}/telegram/password`, options)
      .then((r) => r.data),

  /** PUT /api/v1/agents/:id/telegram/username — установить или сменить @username */
  changeTelegramUsername: (id: string, body: TelegramUsernameInput, options?: AxiosRequestConfig) =>
    apiClient
      .put<TelegramUsernameResponse>(`/agents/${id}/telegram/username`, body, options)
      .then((r) => r.data),

  /**
   * PUT /api/v1/agents/:id/telegram/password — установить или сменить облачный пароль.
   * edit_2fa проверяет простые числа и может отвечать долго, поэтому таймаут
   * увеличен только у этой операции.
   */
  changeTelegramPassword: (id: string, body: TelegramPasswordInput, options?: AxiosRequestConfig) =>
    apiClient
      .put<TelegramPasswordResponse>(`/agents/${id}/telegram/password`, body, {
        ...options,
        timeout: 120_000,
      })
      .then((r) => r.data),

  /** DELETE /api/v1/agents/:id */
  remove: (id: string, options?: AxiosRequestConfig) =>
    apiClient.delete<void>(`/agents/${id}`, options).then(() => undefined),

  /** POST /api/v1/agents/:id/context/reset — the agent forgets recent conversations */
  resetContext: (id: string, options?: AxiosRequestConfig) =>
    apiClient
      .post<{ context_reset_at: string }>(`/agents/${id}/context/reset`, undefined, options)
      .then((r) => r.data),

  /** GET /api/v1/agents/:id/warmup — ограничение Telegram и режим восстановления */
  getWarmupState: (id: string, options?: AxiosRequestConfig) =>
    apiClient.get<WarmupState>(`/agents/${id}/warmup`, options).then((r) => r.data),

  /** POST /api/v1/agents/:id/warmup/recovery — включить восстановление (409, если не ограничен) */
  startWarmupRecovery: (id: string, options?: AxiosRequestConfig) =>
    apiClient.post<WarmupState>(`/agents/${id}/warmup/recovery`, undefined, options).then((r) => r.data),

  /** GET /api/v1/agents/:id/chats — диалоги аккаунта (409, пока агент не запущен) */
  listChats: (id: string, options?: AxiosRequestConfig) =>
    apiClient.get<AgentChat[]>(`/agents/${id}/chats`, options).then((r) => r.data),

  /** GET /api/v1/agents/:id/conversation — cursor page, newest first */
  getConversation: (id: string, limit = 50, before?: string | null, beforeId?: string | null, options?: AxiosRequestConfig) =>
    apiClient
      .get<ConversationPage>(`/agents/${id}/conversation`, {
        ...options,
        params: before
          ? { limit, before, ...(beforeId ? { before_id: beforeId } : {}) }
          : { limit },
      })
      .then((r) => r.data),

  /** POST /api/v1/agents/:id/messages/trigger */
  triggerMessage: (id: string, body: TriggerMessageInput, options?: AxiosRequestConfig) =>
    apiClient
      .post<TriggerMessageResponse>(`/agents/${id}/messages/trigger`, body, options)
      .then((r) => r.data),

  /**
   * POST /api/v1/agents/:id/media — картинка для настроек агента.
   * Бакет закрыт для клиентских ролей, поэтому файл идёт через бэкенд.
   * Content-Type не задаётся вручную: его ставит браузер вместе с boundary.
   */
  uploadMedia: (id: string, file: File, options?: AxiosRequestConfig) => {
    const body = new FormData();
    body.append('file', file);
    return apiClient
      .post<UploadedMedia>(`/agents/${id}/media`, body, {
        ...options,
        headers: { 'Content-Type': undefined },
      })
      .then((r) => r.data);
  },

  /** GET /api/v1/agents/:id/media-link/:path — подписанная ссылка на объект Storage */
  signMediaLink: (id: string, storagePath: string, options?: AxiosRequestConfig) =>
    apiClient
      .get<MediaLink>(`/agents/${id}/media-link/${encodeMediaPath(storagePath)}`, options)
      .then((r) => r.data),
};

export const onboardingApi = {
  /** POST /api/v1/onboarding/telegram */
  startTelegram: (body: OnboardingTelegramInput, options?: AxiosRequestConfig) =>
    apiClient
      .post<OnboardingPublicStatus>('/onboarding/telegram', body, options)
      .then((r) => r.data),

  /** POST /api/v1/onboarding/:onboardingId/telegram/code */
  submitCode: (onboardingId: string, body: TelegramCodeInput, options?: AxiosRequestConfig) =>
    apiClient
      .post<OnboardingPublicStatus>(`/onboarding/${onboardingId}/telegram/code`, body, options)
      .then((r) => r.data),

  /** POST /api/v1/onboarding/:onboardingId/agent */
  finalizeAgent: (onboardingId: string, body: FinalizeAgentInput, options?: AxiosRequestConfig) =>
    apiClient
      .post<AgentStatus>(`/onboarding/${onboardingId}/agent`, body, options)
      .then((r) => r.data),
};

export const agentMemoryApi = {
  /** GET /api/v1/agents/:id/memory */
  list: (agentId: string, query?: string, options?: AxiosRequestConfig) =>
    apiClient
      .get<AgentMemory[]>(`/agents/${agentId}/memory`, { ...options, params: query ? { query } : {} })
      .then((r) => r.data),

  /** GET /api/v1/agents/:id/memory/:memoryId/history */
  getHistory: (agentId: string, memoryId: string, options?: AxiosRequestConfig) =>
    apiClient
      .get<MemoryHistoryItem[]>(`/agents/${agentId}/memory/${memoryId}/history`, options)
      .then((r) => r.data),
};

export function createAccountApi(scope: ApiAccountScope | undefined) {
  const options = { accountScope: scope };
  return {
    agents: {
      list: () => agentsApi.list(options),
      get: (id: string) => agentsApi.get(id, options),
      start: (id: string) => agentsApi.start(id, options),
      stop: (id: string) => agentsApi.stop(id, options),
      reload: (id: string) => agentsApi.reload(id, options),
      rebindTelegram: (id: string) => agentsApi.rebindTelegram(id, options),
      confirmRebind: (id: string, body: { onboarding_id: string }) =>
        agentsApi.confirmRebind(id, body, options),
      getTelegramPasswordState: (id: string) =>
        agentsApi.getTelegramPasswordState(id, options),
      changeTelegramUsername: (id: string, body: TelegramUsernameInput) =>
        agentsApi.changeTelegramUsername(id, body, options),
      changeTelegramPassword: (id: string, body: TelegramPasswordInput) =>
        agentsApi.changeTelegramPassword(id, body, options),
      remove: (id: string) => agentsApi.remove(id, options),
      resetContext: (id: string) => agentsApi.resetContext(id, options),
      getWarmupState: (id: string) => agentsApi.getWarmupState(id, options),
      startWarmupRecovery: (id: string) =>
        agentsApi.startWarmupRecovery(id, options),
      listChats: (id: string) => agentsApi.listChats(id, options),
      getConversation: (id: string, limit = 50, before?: string | null, beforeId?: string | null) =>
        agentsApi.getConversation(id, limit, before, beforeId, options),
      triggerMessage: (id: string, body: TriggerMessageInput) =>
        agentsApi.triggerMessage(id, body, options),
      uploadMedia: (id: string, file: File) => agentsApi.uploadMedia(id, file, options),
      signMediaLink: (id: string, path: string) =>
        agentsApi.signMediaLink(id, path, options),
    },
    onboarding: {
      startTelegram: (body: OnboardingTelegramInput) =>
        onboardingApi.startTelegram(body, options),
      submitCode: (id: string, body: TelegramCodeInput) =>
        onboardingApi.submitCode(id, body, options),
      finalizeAgent: (id: string, body: FinalizeAgentInput) =>
        onboardingApi.finalizeAgent(id, body, options),
    },
    memory: {
      list: (id: string, query?: string) => agentMemoryApi.list(id, query, options),
      getHistory: (id: string, memoryId: string) =>
        agentMemoryApi.getHistory(id, memoryId, options),
    },
  };
}
