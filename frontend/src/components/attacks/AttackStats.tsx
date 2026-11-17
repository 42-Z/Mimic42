import {
  attackEndReasonLabel,
  attackLimitLabel,
  attackPace,
  formatAttackDate,
  formatSeconds,
} from '@/lib/attacks/display';
import type { AttackSummary } from '@/types';

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1 truncate font-mono text-sm tabular-nums text-foreground">{value}</dd>
      {hint && <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function AttackStats({ attack }: { attack: AttackSummary }) {
  const pace = attackPace(attack.slowmode_seconds);
  const inFlight = Math.max(0, attack.claimed_count - attack.sent_count);

  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
      <Stat
        label="Отправлено"
        value={String(attack.sent_count)}
        hint={attackLimitLabel(attack.limit_kind, attack.limit_value)}
      />
      <Stat label="В резерве" value={String(inFlight)} hint="подтверждаются отправкой" />
      <Stat
        label="Темп"
        value={formatSeconds(pace.seconds)}
        hint={`${pace.source === 'slowmode' ? 'медленный режим' : 'базовая пауза'} · на мимика`}
      />
      <Stat label="Старт" value={formatAttackDate(attack.started_at)} />
      {attack.finished_at && (
        <Stat label="Финиш" value={formatAttackDate(attack.finished_at)} />
      )}
      {!attack.finished_at && attack.deadline_at && (
        <Stat label="Дедлайн" value={formatAttackDate(attack.deadline_at)} />
      )}
      {attack.end_reason && (
        <Stat
          label="Причина финала"
          value={attackEndReasonLabel(attack.end_reason) ?? attack.end_reason}
        />
      )}
    </dl>
  );
}
