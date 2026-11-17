'use client';

import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Input } from '@/components/ui/input';
import type { AttackLimitKind } from '@/types';

export function AttackLimitFields({
  kind,
  value,
  error,
  onKindChange,
  onValueChange,
}: {
  kind: AttackLimitKind;
  value: number | null;
  error?: string;
  onKindChange: (kind: AttackLimitKind) => void;
  onValueChange: (value: number | null) => void;
}) {
  const isMessages = kind === 'messages';

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <span className="font-mono text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Тип лимита
        </span>
        <ToggleGroup
          type="single"
          value={kind}
          onValueChange={(next) => {
            if (next === 'messages' || next === 'minutes') onKindChange(next);
          }}
          variant="outline"
          aria-label="Тип лимита"
        >
          <ToggleGroupItem value="messages">Сообщения</ToggleGroupItem>
          <ToggleGroupItem value="minutes">Минуты</ToggleGroupItem>
        </ToggleGroup>
      </div>

      <Input
        type="number"
        min={1}
        step={1}
        inputMode="numeric"
        label={isMessages ? 'Лимит сообщений' : 'Длительность, минуты'}
        value={value ?? ''}
        onChange={(event) => {
          const raw = event.target.value;
          if (raw === '') {
            onValueChange(null);
            return;
          }
          const parsed = Number(raw);
          if (Number.isFinite(parsed)) onValueChange(parsed);
        }}
        error={error}
        hint={
          isMessages
            ? 'Общий лимит на всю атаку. После него отправки прекратятся.'
            : 'Срок считается от момента запуска атаки.'
        }
      />
    </div>
  );
}
