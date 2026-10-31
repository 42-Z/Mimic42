import type { AgentState } from './index';

export interface AdminIdentity {
  user_id: string;
  is_admin: boolean;
}

export interface AdminPage<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminUserSummary {
  user_id: string;
  email: string | null;
  display_name: string | null;
  created_at: string;
  agents_total: number;
  states: Partial<Record<AgentState, number>>;
}

export type AdminProxyProtocol = 'socks5' | 'http';

export interface AdminAgentProxy {
  id: string;
  label: string | null;
  protocol: AdminProxyProtocol;
  host: string;
  port: number;
  is_active: boolean;
}

export interface AdminAgentSummary {
  agent_id: string;
  name: string;
  llm_model: string;
  state: AgentState;
  proxy: AdminAgentProxy | null;
}

export interface AdminProxySummary {
  id: string;
  label: string | null;
  protocol: AdminProxyProtocol;
  host: string;
  port: number;
  username: string | null;
  has_password: boolean;
  is_active: boolean;
  agents_total: number;
  onboarding_total: number;
  created_at: string;
  updated_at: string;
}

export interface AdminProxyDetail extends AdminProxySummary {
  created_by: string | null;
}

export interface AdminProxyInput {
  label?: string | null;
  protocol: AdminProxyProtocol;
  host: string;
  port: number;
  username?: string | null;
  password?: string;
  is_active: boolean;
}

export interface UpdateAdminProxy {
  label?: string | null;
  protocol?: AdminProxyProtocol;
  host?: string;
  port?: number;
  username?: string | null;
  password?: string;
  is_active?: boolean;
}

export interface AdminProxyCheckResult {
  ok: boolean;
  latency_ms: number | null;
  error: string | null;
}

export interface AdminProxyImportInput {
  text: string;
  protocol: AdminProxyProtocol;
  is_active: boolean;
}

export interface AdminProxyImportResult {
  imported: number;
  skipped: number;
  errors: string[];
}

export interface AdminUserDetail {
  profile: AdminUserSummary;
  agents: AdminPage<AdminAgentSummary>;
}

export type AdminPresetKind = 'all' | 'official' | 'published';

export interface AdminPresetSummary {
  id: string;
  owner_id: string | null;
  owner_name: string | null;
  title: string;
  summary: string;
  sort_order: number;
  is_active: boolean;
  published_at: string | null;
  updated_at: string;
}

export interface AdminPresetDetail extends AdminPresetSummary {
  body: string;
  settings: Record<string, unknown> | null;
}

export interface CreateAdminPreset {
  title: string;
  summary: string;
  body: string;
  settings?: Record<string, unknown> | null;
  sort_order?: number;
}

export interface UpdateAdminPreset {
  title?: string;
  summary?: string;
  body?: string;
  settings?: Record<string, unknown> | null;
  sort_order?: number;
}

export interface PublicTelegramSettings {
  api_id: number | null;
  api_hash: string | null;
  has_api_hash: boolean;
  source: 'database' | 'unconfigured';
  updated_at: string | null;
  updated_by: string | null;
}

export interface SaveTelegramSettings {
  api_id: number;
  api_hash: string;
}

export interface ActivityCounts {
  messages: number;
  actions: number;
  errors: number;
}

export interface DailyActivity extends ActivityCounts {
  date: string;
}

export interface AdminStatistics {
  users: number;
  agents: number;
  states: Partial<Record<AgentState, number>>;
  input_tokens: number;
  output_tokens: number;
  period_days: 7 | 30;
  since: string;
  until: string;
  totals: ActivityCounts;
  daily: DailyActivity[];
}
