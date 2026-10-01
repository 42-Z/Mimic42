'use client';

import type * as React from 'react';
import { ChevronDown } from 'lucide-react';
import type { ActivityGroup } from '@/lib/activity/group';
import { TurnCard } from './TurnCard';

interface LifecycleStackProps {
  items: ActivityGroup;
  /** Состояние раскрытия держит родитель: стек переживает пересборку групп. */
  isOpen: boolean;
  onToggle: (open: boolean) => void;
}

export function LifecycleStack({ items, isOpen, onToggle }: LifecycleStackProps) {
  return (
    <details
      open={isOpen}
      onToggle={(event: React.SyntheticEvent<HTMLDetailsElement>) =>
        onToggle(event.currentTarget.open)
      }
      className="group border-b border-border/70 last:border-b-0"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 pr-3.5 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        <div className="min-w-0 flex-1">
          <TurnCard item={items[0]} />
        </div>
        <span className="shrink-0 rounded-sm border border-border px-1.5 font-mono text-xs tabular-nums text-muted-foreground" aria-label={`Всего событий: ${items.length}`}>
          ×{items.length}
        </span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="border-t border-border/70">
        {items.map((item) => <TurnCard key={item.id} item={item} />)}
      </div>
    </details>
  );
}
