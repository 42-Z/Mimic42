import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { getSupabaseClient } from '@/lib/supabase/client';
import type { ApiError } from '@/types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

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

// ── Request interceptor — attach JWT ─────────────────────────────────────────
apiClient.interceptors.request.use(
  async (config: InternalAxiosRequestConfig) => {
    try {
      const supabase = getSupabaseClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (session?.access_token) {
        config.headers.Authorization = `Bearer ${session.access_token}`;
      }
    } catch {
      // If getting the session fails, proceed without the token.
      // The backend will return 401 and the response interceptor will handle it.
    }

    return config;
  },
  (error: unknown) => Promise.reject(error)
);

// ── Response interceptor — normalize errors ───────────────────────────────────
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
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
        message = 'Конфликт: ресурс уже существует.';
        break;
      case 422:
        message = formatValidationError(detail);
        break;
      case 428:
        message = 'Требуется 2FA пароль.';
        break;
      case 429:
        message = 'Слишком много запросов. Подождите немного.';
        break;
      case 500:
        message = 'Внутренняя ошибка сервера.';
        break;
      case 503:
        message = 'Сервер временно недоступен.';
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
  AgentRecord,
  AgentStatus,
  AgentMessageRecord,
  AgentActivity,
  OnboardingTelegramInput,
  OnboardingPublicStatus,
  TelegramCodeInput,
  FinalizeAgentInput,
  TriggerMessageInput,
  TriggerMessageResponse,
  AgentMemory,
  MemoryHistoryItem,
} from '@/types';

export const agentsApi = {
  /** GET /api/v1/agents */
  list: () =>
    apiClient.get<AgentRecord[]>('/agents').then((r) => r.data),

  /** GET /api/v1/agents/:id */
  get: (id: string) =>
    apiClient.get<AgentStatus>(`/agents/${id}`).then((r) => r.data),

  /** POST /api/v1/agents/:id/start */
  start: (id: string) =>
    apiClient.post<void>(`/agents/${id}/start`).then(() => undefined),

  /** POST /api/v1/agents/:id/stop */
  stop: (id: string) =>
    apiClient.post<void>(`/agents/${id}/stop`).then(() => undefined),

  /** DELETE /api/v1/agents/:id */
  remove: (id: string) =>
    apiClient.delete<void>(`/agents/${id}`).then(() => undefined),

  /** GET /api/v1/agents/:id/messages */
  getMessages: (id: string, limit = 50) =>
    apiClient
      .get<AgentMessageRecord[]>(`/agents/${id}/messages`, { params: { limit } })
      .then((r) => r.data),

  /** GET /api/v1/agents/:id/actions */
  getActions: (id: string, limit = 50) =>
    apiClient
      .get<AgentActivity[]>(`/agents/${id}/actions`, { params: { limit } })
      .then((r) => r.data),

  /** POST /api/v1/agents/:id/messages/trigger */
  triggerMessage: (id: string, body: TriggerMessageInput) =>
    apiClient
      .post<TriggerMessageResponse>(`/agents/${id}/messages/trigger`, body)
      .then((r) => r.data),
};

export const onboardingApi = {
  /** POST /api/v1/onboarding/telegram */
  startTelegram: (body: OnboardingTelegramInput) =>
    apiClient
      .post<OnboardingPublicStatus>('/onboarding/telegram', body)
      .then((r) => r.data),

  /** POST /api/v1/onboarding/:onboardingId/telegram/code */
  submitCode: (onboardingId: string, body: TelegramCodeInput) =>
    apiClient
      .post<OnboardingPublicStatus>(`/onboarding/${onboardingId}/telegram/code`, body)
      .then((r) => r.data),

  /** POST /api/v1/onboarding/:onboardingId/agent */
  finalizeAgent: (onboardingId: string, body: FinalizeAgentInput) =>
    apiClient
      .post<AgentStatus>(`/onboarding/${onboardingId}/agent`, body)
      .then((r) => r.data),
};

export const agentMemoryApi = {
  /** GET /api/v1/agents/:id/memory */
  list: (agentId: string, query?: string) =>
    apiClient
      .get<AgentMemory[]>(`/agents/${agentId}/memory`, { params: query ? { query } : {} })
      .then((r) => r.data),

  /** GET /api/v1/agents/:id/memory/:memoryId/history */
  getHistory: (agentId: string, memoryId: string) =>
    apiClient
      .get<MemoryHistoryItem[]>(`/agents/${agentId}/memory/${memoryId}/history`)
      .then((r) => r.data),
};
