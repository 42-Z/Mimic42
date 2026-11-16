import { format } from 'date-fns';
import { ru } from 'date-fns/locale';

import type {
  AttackAgent,
  AttackDetail,
  AttackLimitKind,
  AttackStatus,
  AttackSummary,
} from '@/types';
import type { AttackEditFormState } from './types';

/** База темпа, когда у группы обсуждения нет медленного режима. */
export const DEFAULT_ATTACK_PAUSE_SECONDS = 10;

export interface AttackPace {
  seconds: number;
  source: 'slowmode' | 'default';
  label: string;
}

export interface AttackProgressView {
  /** Процент выполнения для шкалы и `aria-valuenow`. */
  value: number;
  label: string;
  detail: string;
}

export function pluralize(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

export function formatSeconds(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 60) return `${seconds} с`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return rest > 0 ? `${minutes} мин ${rest} с` : `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes > 0 ? `${hours} ч ${restMinutes} мин` : `${hours} ч`;
}

export function formatAttackDate(value: string | null): string {
  if (!value) return '—';
  return format(new Date(value), 'd MMM, HH:mm', { locale: ru });
}

export function attackTitle(attack: Pick<AttackSummary, 'title' | 'target_link'>): string {
  const title = attack.title?.trim();
  if (title && title.length > 0) return title;
  return attackChannelName(attack.target_link);
}

export function attackChannelName(link: string): string {
  try {
    const url = new URL(link.includes('://') ? link : `https://${link}`);
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts[0] === 'c') return 'приватный канал';
    return parts[0] ? `@${parts[0]}` : link;
  } catch {
    return link;
  }
}

export function targetHref(link: string): string {
  return /^https?:\/\//i.test(link) ? link : `https://${link}`;
}

export function attackPace(slowmodeSeconds: number | null | undefined): AttackPace {
  const hasSlowmode = typeof slowmodeSeconds === 'number' && slowmodeSeconds > 0;
  const seconds = hasSlowmode ? slowmodeSeconds : DEFAULT_ATTACK_PAUSE_SECONDS;
  return {
    seconds,
    source: hasSlowmode ? 'slowmode' : 'default',
    label: `${formatSeconds(seconds)} · ${hasSlowmode ? 'медленный режим' : 'базовая пауза'}`,
  };
}

export function attackProgress(
  attack: Pick<
    AttackSummary,
    | 'status'
    | 'limit_kind'
    | 'limit_value'
    | 'sent_count'
    | 'started_at'
    | 'finished_at'
  >,
  now = Date.now(),
): AttackProgressView {
  if (attack.limit_kind === 'minutes') {
    const totalSeconds = Math.max(0, attack.limit_value * 60);
    const startedAt = attack.started_at ? new Date(attack.started_at).getTime() : null;
    const endedAt = attack.finished_at ? new Date(attack.finished_at).getTime() : null;
    const elapsedSeconds = startedAt
      ? Math.max(0, Math.floor(((endedAt ?? now) - startedAt) / 1000))
      : 0;
    const cappedSeconds = Math.min(elapsedSeconds, totalSeconds);
    const value =
      totalSeconds > 0 ? Math.min(100, Math.round((cappedSeconds / totalSeconds) * 100)) : 0;
    const remainingSeconds = Math.max(0, totalSeconds - elapsedSeconds);

    return {
      value,
      label: `${formatSeconds(cappedSeconds)} / ${formatSeconds(totalSeconds)}`,
      detail:
        attack.status === 'running'
          ? `До завершения ${formatSeconds(remainingSeconds)}`
          : `Срок атаки ${formatSeconds(totalSeconds)}`,
    };
  }

  const limit = Math.max(1, attack.limit_value);
  const sent = Math.max(0, attack.sent_count);
  const value = Math.min(100, Math.round((sent / limit) * 100));
  const remaining = Math.max(0, limit - sent);

  return {
    value,
    label: `${sent} / ${limit} ${pluralize(limit, 'комментарий', 'комментария', 'комментариев')}`,
    detail:
      attack.status === 'running'
        ? `${remaining} ${pluralize(remaining, 'остался', 'осталось', 'осталось')} до лимита`
        : `Лимит ${limit} ${pluralize(limit, 'комментарий', 'комментария', 'комментариев')}`,
  };
}

export function attackLimitLabel(
  kind: AttackLimitKind,
  value: number,
): string {
  return kind === 'messages'
    ? `${value} ${pluralize(value, 'сообщение', 'сообщения', 'сообщений')}`
    : `${value} ${pluralize(value, 'минута', 'минуты', 'минут')}`;
}

export function attackStatusLabel(status: AttackStatus): string {
  switch (status) {
    case 'draft':
      return 'Черновик';
    case 'running':
      return 'Идёт';
    case 'finished':
      return 'Завершена';
    case 'cancelled':
      return 'Отменена';
  }
}

export function exitReasonLabel(reason: string | null): string | null {
  switch (reason) {
    case 'attack_finished':
      return 'атака завершена';
    case 'attack_cancelled':
      return 'атака отменена';
    case 'paused':
      return 'пауза';
    case 'moved':
      return 'перенесён';
    case 'agent_stopped':
      return 'агент остановлен';
    case 'agent_removed':
      return 'агент удалён';
    case 'peer_flood':
      return 'ограничение Telegram';
    case 'banned_in_channel':
      return 'запрет писать в канале';
    case 'join_blocked':
      return 'не удалось вступить';
    case 'session_revoked':
      return 'сессия отозвана';
    case 'start_failed':
      return 'не удалось запустить';
    case 'target_unavailable':
      return 'пост недоступен';
    case 'send_failed':
      return 'отправка не удалась';
    default:
      return null;
  }
}

export function attackAgentStatusLabel(agent: AttackAgent): string {
  if (agent.status === 'active') return 'в атаке';
  if (agent.status === 'assigned') return 'назначен';
  return exitReasonLabel(agent.exit_reason) ?? 'выбыл';
}

export function attackEndReasonLabel(reason: string | null): string | null {
  switch (reason) {
    case 'limit_reached':
      return 'лимит достигнут';
    case 'deadline':
      return 'срок истёк';
    case 'cancelled_by_user':
      return 'отменена пользователем';
    case 'no_agents':
      return 'не осталось мимиков';
    case 'all_blocked':
      return 'все мимики ограничены';
    case 'target_unavailable':
      return 'пост недоступен';
    default:
      return null;
  }
}

export function isArchiveStatus(status: AttackStatus): boolean {
  return status === 'finished' || status === 'cancelled';
}

export function isEditableStatus(status: AttackStatus): boolean {
  return status === 'draft' || status === 'running';
}

export function editInitialFromAttack(attack: AttackDetail): AttackEditFormState {
  return {
    version: attack.version,
    title: attack.title ?? '',
    texts: attack.texts,
    images: attack.media.map(({ path, name }) => ({ path, name })),
    limit_kind: attack.limit_kind,
    message_limit: attack.limit_kind === 'messages' ? attack.limit_value : null,
    duration_minutes: attack.limit_kind === 'minutes' ? attack.limit_value : null,
  };
}
