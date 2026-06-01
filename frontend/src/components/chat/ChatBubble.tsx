'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import type { ConversationTurn } from '@/types';
import { format } from 'date-fns';

interface ChatBubbleProps {
  turn: ConversationTurn;
}

export function ChatBubble({ turn }: ChatBubbleProps) {
  const time = format(new Date(turn.timestamp), 'HH:mm');

  // Only incoming
  if (turn.direction === 'incoming') {
    return (
      <div className="flex justify-start mb-2">
        <div className="max-w-[70%]">
          <div className="text-[11px] text-void-500 mb-0.5">{turn.peer_name || turn.peer_id}</div>
          <div className="bg-void-800 text-void-100 rounded-2xl rounded-tl-md px-4 py-2 text-sm">
            {turn.incoming}
          </div>
          <div className="text-[10px] text-void-600 text-right mt-0.5">{time}</div>
        </div>
      </div>
    );
  }

  // Only outgoing
  if (turn.direction === 'outgoing') {
    return (
      <div className="flex justify-end mb-2">
        <div className="max-w-[70%]">
          <div className="text-[11px] text-void-500 mb-0.5 text-right">{turn.agent_name || 'Агент'}</div>
          <div className="bg-plasma-950 text-plasma-100 rounded-2xl rounded-tr-md px-4 py-2 text-sm border border-plasma-900/40">
            {turn.outgoing}
          </div>
          <div className="text-[10px] text-void-600 text-right mt-0.5">{time}</div>
        </div>
      </div>
    );
  }

  // Both: incoming + outgoing
  return (
    <div className="space-y-2 mb-4">
      {/* Incoming */}
      <div className="flex justify-start">
        <div className="max-w-[70%]">
          <div className="text-[11px] text-void-500 mb-0.5">{turn.peer_name || turn.peer_id}</div>
          <div className="bg-void-800 text-void-100 rounded-2xl rounded-tl-md px-4 py-2 text-sm">
            {turn.incoming}
          </div>
        </div>
      </div>

      {/* Outgoing */}
      <div className="flex justify-end">
        <div className="max-w-[70%]">
          <div className="text-[11px] text-void-500 mb-0.5 text-right">{turn.agent_name || 'Агент'}</div>
          <div className="bg-plasma-950 text-plasma-100 rounded-2xl rounded-tr-md px-4 py-2 text-sm border border-plasma-900/40">
            {turn.outgoing}
          </div>
          <div className="text-[10px] text-void-600 text-right mt-0.5">{time}</div>
        </div>
      </div>
    </div>
  );
}
