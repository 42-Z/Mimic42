'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown, Clock, RefreshCw } from 'lucide-react';
import { format } from 'date-fns';
import { ru } from 'date-fns/locale';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { sanitizeText } from '@/lib/sanitize';
import { cn } from '@/lib/utils';
import type { AgentMemory } from '@/types';

export function MemoryCard({
  memory,
  onShowHistory,
}: {
  memory: AgentMemory;
  onShowHistory: (memoryId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [clipped, setClipped] = useState(false);
  const textRef = useRef<HTMLParagraphElement>(null);
  const textId = useId();
  const content = sanitizeText(memory.memory);

  useEffect(() => {
    const text = textRef.current;
    if (!text || expanded) return;
    const measure = () => setClipped(text.scrollHeight > text.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(text);
    return () => observer.disconnect();
  }, [content, expanded]);

  return (
    <Card variant="glass" padding="sm" className="min-w-0 border-border/80 hover:border-primary/30 transition-colors">
      <p
        id={textId}
        ref={textRef}
        className={cn(
          'text-foreground text-sm leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]',
          !expanded && 'line-clamp-4',
        )}
      >
        {content}
      </p>
      {(clipped || expanded) && (
        <Button
          type="button"
          variant="ghost"
          size="xs"
          className="mt-2"
          aria-expanded={expanded}
          aria-controls={textId}
          onClick={() => setExpanded((value) => !value)}
          rightIcon={<ChevronDown className={cn('h-3 w-3', expanded && 'rotate-180')} aria-hidden="true" />}
        >
          {expanded ? 'Свернуть' : 'Показать полностью'}
        </Button>
      )}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-2">
        <span className="font-mono text-[10px] text-muted-foreground flex items-center gap-1.5">
          <Clock className="h-3 w-3" aria-hidden="true" />
          {memory.created_at
            ? format(new Date(memory.created_at), 'dd.MM.yyyy HH:mm', { locale: ru })
            : 'Неизвестно'}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          onClick={() => onShowHistory(memory.id)}
          leftIcon={<RefreshCw className="h-3 w-3" aria-hidden="true" />}
          className="text-muted-foreground transition-colors hover:bg-muted/40 hover:text-primary"
        >
          История
        </Button>
      </div>
    </Card>
  );
}
