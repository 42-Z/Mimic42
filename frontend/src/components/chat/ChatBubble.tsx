'use client';

import React, { useState } from 'react';
import { cn } from '@/lib/utils';
import type { ConversationTurn } from '@/types';
import { format } from 'date-fns';
import { Zap, ChevronDown, ChevronUp } from 'lucide-react';

interface ChatBubbleProps {
  turn: ConversationTurn;
}

function ToolCard({ name, status }: { name: string; status: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      onClick={() => setExpanded(!expanded)}
      className={cn(
        'flex items-center gap-2 mt-1 px-2 py-1 rounded-md text-[11px] cursor-pointer transition-colors',
        status === 'succeeded'
          ? 'bg-amber-950/40 border border-amber-900/60 text-amber-400'
          : 'bg-crimson-950/40 border border-crimson-900/60 text-crimson-400',
      )}
    >
      <Zap className="h-3 w-3 shrink-0" />
      <span className="truncate flex-1">{name}</span>
      <span className="text-[10px] opacity-60">{status}</span>
      {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
    </div>
  );
}

export function ChatBubble({ turn }: ChatBubbleProps) {
  const time = format(new Date(turn.timestamp), 'HH:mm');

  // Check if this is a tool call turn (starts with [ and has ])
  const isToolCall = turn.outgoing?.startsWith('[') && turn.outgoing?.includes(']');

  if (isToolCall) {
    const match = turn.outgoing.match(/^\[(.+?)\]\s*(.+?)?$/);
    const toolName = match?.[1] || 'tool';
    const status = match?.[2]?.trim() || 'unknown';
    return (
      <div className="flex justify-center mb-2">
        <div className="max-w-[70%]">
          <ToolCard name={toolName} status={status} />
          <div className="text-[10px] text-void-600 text-center mt-0.5">{time}</div>
        </div>
      </div>
    );
  }

  // Only incoming
  if (turn.direction === 'incoming') {
    return (
      <div className="flex justify-start mb-2">
        <div className="max-w-[85%] sm:max-w-[70%]">
          <div className="text-[11px] text-void-500 mb-0.5 truncate">{turn.peer_name || turn.peer_id}</div>
          <div className="bg-void-800 text-void-100 rounded-2xl rounded-tl-md px-4 py-2 text-sm break-words">
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
        <div className="max-w-[85%] sm:max-w-[70%]">
          <div className="text-[11px] text-void-500 mb-0.5 text-right truncate">{turn.agent_name || 'Агент'}</div>
          <div className="bg-plasma-950 text-plasma-100 rounded-2xl rounded-tr-md px-4 py-2 text-sm border border-plasma-900/40 break-words">
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
        <div className="max-w-[85%] sm:max-w-[70%]">
          <div className="text-[11px] text-void-500 mb-0.5 truncate">{turn.peer_name || turn.peer_id}</div>
          <div className="bg-void-800 text-void-100 rounded-2xl rounded-tl-md px-4 py-2 text-sm break-words">
            {turn.incoming}
          </div>
        </div>
      </div>

      {/* Outgoing */}
      <div className="flex justify-end">
        <div className="max-w-[85%] sm:max-w-[70%]">
          <div className="text-[11px] text-void-500 mb-0.5 text-right truncate">{turn.agent_name || 'Агент'}</div>
          <div className="bg-plasma-950 text-plasma-100 rounded-2xl rounded-tr-md px-4 py-2 text-sm border border-plasma-900/40 break-words">
            {turn.outgoing}
          </div>
          <div className="text-[10px] text-void-600 text-right mt-0.5">{time}</div>
        </div>
      </div>
    </div>
  );
}
