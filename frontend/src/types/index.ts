// ============================================================
// BACKEND TYPES — Mirror of FastAPI Pydantic models
// ============================================================

/**
 * Agent state machine states
 */
export type AgentState =
  | 'draft'
  | 'stopped'
  | 'starting'
  | 'running'
  | 'stopping'
  | 'error';

/**
 * GET /api/v1/agents — list item
 */
export interface AgentRecord {
  agent_id: string;    // UUID
  owner_id: string;    // UUID
  name: string;
  state: AgentState;
}

/**
 * GET /api/v1/agents/{id} — single agent status
 */
export interface AgentStatus {
  agent_id: string;
  owner_id: string;
  state: AgentState;
}

/**
 * Message direction — mirrors the `agent_message_direction` Postgres enum
 */
export type AgentMessageDirection =
  | 'incoming'
  | 'outgoing'
  | 'dashboard_trigger'
  | 'agent_response'
  | 'tool_call'
  | 'tool_result';

/**
 * GET /api/v1/agents/{id}/messages — message record
 */
export interface AgentMessageRecord {
  id: string;
  agent_id: string;
  peer: string;        // telegram peer id/username
  role: 'user' | 'assistant' | string;
  content: string;
  created_at: string;  // ISO 8601
  direction?: AgentMessageDirection;
  thread_id?: string;
  payload?: Record<string, any>;
}

/**
 * Event/action status
 */
export type EventStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';

/**
 * GET /api/v1/agents/{id}/actions — activity/event record
 */
export interface AgentActivity {
  id?: string;
  agent_id: string;
  event_type: string;
  status: EventStatus;
  created_at: string;
  payload?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  error: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

/**
 * POST /api/v1/onboarding/telegram — initiate telegram auth
 * Input body
 */
export interface OnboardingTelegramInput {
  phone_number: string;
  onboarding_id?: string | null;
}

/**
 * Telegram authorization status
 */
export type OnboardingAuthorizationStatus =
  | 'not_started'
  | 'code_requested'
  | 'password_required'
  | 'authorized'
  | 'error';

export type TelegramAuthorizationStatus = OnboardingAuthorizationStatus | 'revoked';/**
 * POST /api/v1/onboarding/telegram — response
 */
export interface OnboardingPublicStatus {
  onboarding_id: string;
  owner_id: string;
  phone_number: string;
  authorization_status: OnboardingAuthorizationStatus;
}

/**
 * POST /api/v1/onboarding/{id}/telegram/code — body
 */
export interface TelegramCodeInput {
  code: string;
  password?: string;
}

/**
 * POST /api/v1/onboarding/{id}/agent — body
 */
export interface FinalizeAgentInput {
  name: string;
  soul_prompt: string;
}

/**
 * POST /api/v1/agents/{id}/messages/trigger — body
 */
export interface TriggerMessageInput {
  peer: string;
  text: string;
}

/**
 * POST /api/v1/agents/{id}/messages/trigger — response
 */
export interface TriggerMessageResponse {
  sent: boolean;
  message_id?: string;
  error?: string;
}

// ============================================================
// SUPABASE TABLE TYPES
// ============================================================

/**
 * agents table row
 */
export interface AgentRow {
  id: string;                    // UUID
  owner_id: string;              // UUID - foreign key to auth.users
  name: string;
  status: AgentState;
  soul_prompt: string | null;
  settings: Record<string, unknown> | null;
  last_started_at: string | null;
  last_stopped_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * agent_messages table row
 */
export interface AgentMessageRow {
  id: string;
  agent_id: string;
  peer?: string;       // not a column: the peer lives in payload
  role: string;
  content: string;
  direction: AgentMessageDirection | null;
  thread_id: string | null;
  created_at: string;
  payload?: Record<string, any>;
}

/**
 * agent_events table row
 */
export interface AgentEventRow {
  id: string;
  agent_id: string;
  event_type: string;
  status: EventStatus;
  error: string | null;
  payload: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

/**
 * telegram_sessions table row
 */
export interface TelegramSessionRow {
  id: string;
  agent_id: string;
  phone_number: string | null;
  authorization_status: TelegramAuthorizationStatus;
  last_authorized_at: string | null;
  last_error: string | null;
  api_id: number | null;
  // api_hash intentionally omitted — sensitive
  created_at: string;
  updated_at: string;
}

/**
 * message_threads table row
 */
export interface MessageThreadRow {
  id: string;
  agent_id: string;
  telegram_peer_id: string;
  title: string | null;
  metadata: Record<string, unknown> | null;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * profiles table row
 */
export interface ProfileRow {
  id: string;         // matches auth.users.id
  email: string | null;
  display_name: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * agent_onboarding_sessions table row
 */
export interface OnboardingSessionRow {
  id: string;           // onboarding_id used in API calls
  owner_id: string;
  agent_name: string | null;
  soul_prompt: string | null;
  authorization_status: OnboardingAuthorizationStatus;
  phone_number: string | null;
  completed_agent_id: string | null;
  created_at: string;
  updated_at: string;
}

// ============================================================
// UI / APPLICATION TYPES
// ============================================================


/**
 * Onboarding step enum
 */
export type OnboardingStep =
  | 'name'
  | 'soul'
  | 'telegram_credentials'
  | 'telegram_code'
  | 'telegram_2fa'
  | 'finalize';

/**
 * Onboarding state derived from DB record
 */
export interface OnboardingState {
  session: OnboardingSessionRow | null;
  currentStep: OnboardingStep;
  isLoading: boolean;
  error: string | null;
}

/**
 * Agent tab IDs
 */
export type AgentTab = 'settings' | 'logs' | 'actions' | 'telegram' | 'analytics' | 'memory';

/**
 * KPI Dashboard metrics
 */
export interface DashboardKPIs {
  contacts_today: number;
  messages_today: number;
  actions_today: number;
  errors_today: number;
}

/**
 * Toast notification
 */
export type ToastVariant = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
  id: string;
  message: string;
  variant: ToastVariant;
  duration?: number;
}

/**
 * API error shape
 */
export interface ApiError {
  status: number;
  message: string;
  detail?: string | Record<string, unknown>;
}

/**
 * Analytics data point
 */
export interface AnalyticsDataPoint {
  date: string;
  messages: number;
  actions: number;
  errors: number;
}

/**
 * Form state for agent settings
 */
export interface AgentSettingsForm {
  name: string;
  soul_prompt: string;
  settings: Record<string, unknown>;
}

/**
 * Realtime event payload from Supabase
 */
export interface RealtimePayload<T> {
  eventType: 'INSERT' | 'UPDATE' | 'DELETE';
  new: T;
  old: Partial<T>;
  schema: string;
  table: string;
}

export interface AgentMemory {
  id: string;
  memory: string;
  user_id: string;
  hash?: string;
  created_at?: string;
  updated_at?: string;
}

export interface MemoryHistoryItem {
  id: string;
  memory_id: string;
  prev_value: string | null;
  new_value: string | null;
  event_type: string;
  created_at: string;
  updated_at?: string | null;
  user_id?: string | null;
}

