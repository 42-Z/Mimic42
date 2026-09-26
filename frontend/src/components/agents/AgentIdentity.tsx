import { sanitizeText } from '@/lib/sanitize';

// ── Agent Identity ────────────────────────────────────────────────────────────
// Прозвище агента + его @юзернейм в Telegram + подпись под ними.

export interface AgentIdentityProps {
  name: string;
  /** Юзернейм Telegram без «@» (или с ним — префикс нормализуется). */
  username?: string | null;
  subtitle?: string | null;
  nameClassName?: string;
  className?: string;
}

/** Юзернейм в готовом к показу виде: без «@», без мусора; пустой → null. */
export function formatTelegramUsername(username: string | null | undefined): string | null {
  const clean = sanitizeText(username).replace(/^@+/, '').trim();
  return clean.length > 0 ? clean : null;
}

export function AgentIdentity({
  name,
  username,
  subtitle,
  nameClassName,
  className,
}: AgentIdentityProps) {
  const handle = formatTelegramUsername(username);
  const cleanName = sanitizeText(name);

  return (
    <div className={className ?? 'min-w-0'}>
      <div className="flex items-baseline gap-2 min-w-0">
        <p className={nameClassName ?? 'font-display text-sm font-bold text-void-100 truncate'}>
          {cleanName}
        </p>
        {handle && (
          <span className="font-mono text-xs text-plasma-400 shrink-0">@{handle}</span>
        )}
      </div>
      {subtitle && (
        <p className="font-mono text-xs text-void-400 truncate">{subtitle}</p>
      )}
    </div>
  );
}
