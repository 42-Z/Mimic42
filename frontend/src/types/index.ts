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
 * GET /api/v1/agents/{id}/messages — message record
 */
export interface AgentMessageRecord {
  id: string;
  agent_id: string;
  peer: string;        // telegram peer id/username
  peer_name: string;    // human-readable sender name (e.g. "Саша")
  agent_name: string;   // human-readable agent name (e.g. "Акакий 42")
  role: 'user' | 'assistant' | string;
  content: string;
  created_at: string;  // ISO 8601
  direction?: 'incoming' | 'outgoing' | 'agent_response' | 'dashboard_trigger' | string;
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
  error: string | null;
  metadata?: Record<string, unknown>;
}

/**
 * POST /api/v1/onboarding/telegram — initiate telegram auth
 * Input body
 */
export interface OnboardingTelegramInput {
  api_id: number;
  api_hash: string;
  phone_number: string;
  onboarding_id?: string;
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
  id: string;           // UUID
  owner_id: string;     // UUID - foreign key to auth.users
  name: string;
  state: AgentState;
  soul_prompt: string | null;
  settings: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

/**
 * agent_messages table row
 */
export interface AgentMessageRow {
  id: string;
  agent_id: string;
  peer: string;
  role: string;
  content: string;
  direction: 'incoming' | 'outgoing' | 'agent_response' | 'dashboard_trigger' | string | null;
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
  metadata: Record<string, unknown> | null;
  created_at: string;
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
  peer: string;
  peer_name: string | null;
  message_count: number;
  last_message_at: string;
  created_at: string;
}

/**
 * profiles table row
 */
export interface ProfileRow {
  id: string;         // matches auth.users.id
  email: string | null;
  display_name: string | null;
  avatar_url: string | null;
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
 * Unified feed item for the live feed — merge of messages and events
 */
export type FeedItemType = 'message' | 'event';

export interface FeedMessage {
  type: 'message';
  id: string;
  timestamp: string;
  peer: string;
  role: string;
  content: string;
  direction?: 'incoming' | 'outgoing';
}

export interface FeedEvent {
  type: 'event';
  id: string;
  timestamp: string;
  event_type: string;
  status: EventStatus;
  error: string | null;
}

export type FeedItem = FeedMessage | FeedEvent;

/**
 * Onboarding step enum
 */
export type OnboardingStep =
  | 'name'
  | 'soul'
  | 'system_prompt'
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
  messages_today: number;
  active_threads: number;
  errors_today: number;
  incoming_week: number;
  isLoading: boolean;
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
  events: number;
  errors: number;
}

/**
 * Thread analytics
 */
export interface ThreadAnalytics {
  peer: string;
  peer_name: string | null;
  message_count: number;
  last_message_at: string;
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

