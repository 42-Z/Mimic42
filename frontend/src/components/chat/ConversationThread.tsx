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
  if (Number.isNaN(date.getTime())) return '';
  try {
    if (isToday(date)) return 'Сегодня';
    if (isYesterday(date)) return 'Вчера';
    return format(date, 'd MMMM', { locale: ru });
  } catch {
    return '';
  }
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
      <div className="flex flex-col items-center justify-center h-full text-void-600 gap-3">
        <div className="h-12 w-12 rounded-full bg-void-800 flex items-center justify-center">
          <span className="text-2xl">💬</span>
        </div>
        <div className="text-center">
          <p className="text-sm font-medium">Нет сообщений</p>
          <p className="text-xs mt-1 opacity-60">Отправьте сообщение боту в Telegram</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-3 sm:p-4">
      {hasMore && onLoadMore && (
        <div className="flex justify-center py-3">
          <button
            onClick={onLoadMore}
            className="text-xs text-plasma-500 hover:text-plasma-300 transition-colors px-4 py-2 rounded-md border border-void-700 hover:border-plasma-800"
          >
            Загрузить ещё
          </button>
        </div>
      )}

      {grouped.map((group, idx) => (
        <div key={group.date || group.turns[0]?.id || idx}>
          <div className="sticky top-0 z-10 text-center py-2 bg-void-950/90 backdrop-blur-sm">
            <span className="text-[10px] text-void-500 bg-void-900 px-3 py-1 rounded-full border border-void-800">
              {group.date}
            </span>
          </div>
          <div className="space-y-1 sm:space-y-2">
            {group.turns.map((turn) => (
              <ChatBubble key={turn.id} turn={turn} />
            ))}
          </div>
        </div>
      ))}

      <div className="h-4" /> {/* bottom spacer */}
    </div>
  );
}
