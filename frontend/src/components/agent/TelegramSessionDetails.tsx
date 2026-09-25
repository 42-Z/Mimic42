import { formatDistanceToNow } from 'date-fns';
import { ru } from 'date-fns/locale';
import { Card } from '@/components/ui/card';
import { maskPhoneNumber } from '@/lib/sanitize';
import { formatTelegramUsername } from '@/components/agents/AgentIdentity';
import { cn } from '@/lib/utils';
import type { TelegramSessionRow } from '@/types';

// ── Telegram Session Details ──────────────────────────────────────────────────
// Реквизиты Telegram-сессии агента. API ID и API HASH сюда не попадают:
// это секреты приложения, показывать их на сайте незачем.

const STATUS_COLORS: Record<string, string> = {
  authorized: 'text-neon-400',
  code_requested: 'text-plasma-400',
  password_required: 'text-amber-400',
  not_started: 'text-void-400',
  error: 'text-crimson-400',
  revoked: 'text-crimson-500',
};

export function TelegramSessionDetails({ session }: { session: TelegramSessionRow }) {
  const handle = formatTelegramUsername(session.username);

  const rows = [
    {
      label: 'Статус авторизации',
      value: session.authorization_status.toUpperCase(),
      // eslint-disable-next-line security/detect-object-injection -- ключ из фиксированного словаря
      color: STATUS_COLORS[session.authorization_status],
    },
    { label: 'Юзернейм', value: handle ? `@${handle}` : '—' },
    { label: 'Номер телефона', value: maskPhoneNumber(session.phone_number) },
    {
      label: 'Последняя авторизация',
      value: session.last_authorized_at
        ? formatDistanceToNow(new Date(session.last_authorized_at), { addSuffix: true, locale: ru })
        : '—',
    },
    {
      label: 'Последняя ошибка',
      value: session.last_error ?? '—',
      color: session.last_error ? 'text-crimson-400' : undefined,
    },
  ];

  return (
    <Card variant="glass" padding="none">
      {rows.map((row, i) => (
        <div
          key={row.label}
          className={cn(
            'flex items-start justify-between px-5 py-4',
            i < rows.length - 1 && 'border-b border-void-800',
          )}
        >
          <span className="font-mono text-xs text-void-400 uppercase tracking-wider">
            {row.label}
          </span>
          <span className={cn('font-mono text-sm text-right', row.color ?? 'text-void-200')}>
            {row.value}
          </span>
        </div>
      ))}
    </Card>
  );
}
