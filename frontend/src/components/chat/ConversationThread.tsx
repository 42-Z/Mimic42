'use client';

import React, { useMemo } from 'react';
import { ChatBubble } from './ChatBubble';
import type { ConversationTurn } from '@/types';
import { format, isToday, isYesterday } from 'date-fns';
import { ru } from 'date-fns/locale';

interface ConversationThreadProps {
  turns: ConversationTurn[];
  isLoading?: boolean;
  hasMore?: boolean;
  onLoadMore?: () => void;
}

function formatDateHeader(dateStr: string): string {
  const date = new Date(dateStr);
  if (isToday(date)) return 'Сегодня';
  if (isYesterday(date)) return 'Вчера';
  return format(date, 'd MMMM', { locale: ru });
}

export function ConversationThread({
  turns,
  isLoading,
  hasMore,
  onLoadMore,
}: ConversationThreadProps) {
  const grouped = useMemo(() => {
    const groups: { date: string; turns: ConversationTurn[] }[] = [];

    for (const turn of turns) {
      const date = formatDateHeader(turn.timestamp);
      const lastGroup = groups[groups.length - 1];
      if (!lastGroup || lastGroup.date !== date) {
        groups.push({ date, turns: [turn] });
      } else {
        lastGroup.turns.push(turn);
      }
    }

    return groups;
  }, [turns]);

  if (isLoading && turns.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-pulse text-void-600 text-sm">Загрузка...</div>
      </div>
    );
  }

  if (turns.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-void-600">
        <p className="text-sm">Нет сообщений</p>
        <p className="text-xs mt-1">Отправьте сообщение боту в Telegram</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4">
      {hasMore && onLoadMore && (
        <div className="flex justify-center py-2">
          <button
            onClick={onLoadMore}
            className="text-xs text-plasma-500 hover:text-plasma-300 transition-colors"
          >
            Загрузить ещё
          </button>
        </div>
      )}

      {grouped.map((group) => (
        <div key={group.date}>
          <div className="sticky top-0 z-10 text-center py-2">
            <span className="text-[10px] text-void-500 bg-void-950 px-2 py-0.5 rounded">
              {group.date}
            </span>
          </div>
          <div className="space-y-2">
            {group.turns.map((turn) => (
              <ChatBubble key={turn.id} turn={turn} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
