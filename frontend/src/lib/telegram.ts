import type { TelegramAuthorizationStatus } from '@/types';

/** Сессия недействительна: Telegram отозвал её или при старте случилась ошибка. */
export function needsRebind(status: TelegramAuthorizationStatus | null | undefined): boolean {
  return status === 'revoked' || status === 'error';
}
