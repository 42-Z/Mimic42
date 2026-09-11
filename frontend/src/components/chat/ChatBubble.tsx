'use client';

import React, { useState } from 'react';
import { cn } from '@/lib/utils';
import type { ConversationTurn, ToolCallRecord } from '@/types';
import { getToolLabel, toolArgs } from '@/lib/toolLabels';
import { format } from 'date-fns';
import { Zap, ChevronDown, ChevronUp, XCircle } from 'lucide-react';

function formatTimeSafe(value: string, fmt: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  try {
    return format(date, fmt);
  } catch {
    return '';
  }
}

function MessageText({ text }: { text: string }) {
  if (!text) return <span className="opacity-50">—</span>;
  return <>{text}</>;
}

function ToolCard({ tool }: { tool: ToolCallRecord }) {
  const [expanded, setExpanded] = useState(false);
  const label = getToolLabel(tool.name, toolArgs(tool.payload?.args));
  const isFailed = tool.status === 'failed';

  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className={cn(
          'flex w-full items-center gap-2 px-3 py-2.5 rounded-md text-xs cursor-pointer transition-colors select-none text-left',
          isFailed
            ? 'bg-crimson-950/40 border border-crimson-900/60 text-crimson-300'
            : 'bg-amber-950/40 border border-amber-900/60 text-amber-300',
        )}
      >
        {isFailed ? (
          <XCircle className="h-3.5 w-3.5 shrink-0" />
        ) : (
          <Zap className="h-3.5 w-3.5 shrink-0" />
        )}
        <span className="truncate flex-1 font-medium">{label}</span>
        {tool.duration_ms > 0 && (
          <span className="text-[10px] opacity-60 tabular-nums">
            {Math.round(tool.duration_ms)} мс
          </span>
        )}
        {expanded ? <ChevronUp className="h-3.5 w-3.5 shrink-0" /> : <ChevronDown className="h-3.5 w-3.5 shrink-0" />}
      </button>

      {expanded && (
        <div className="bg-void-900/60 border border-void-800 rounded-md px-3 py-2 space-y-1.5 text-[11px] text-void-400">
          <div className="flex items-center gap-2">
            <span className="text-void-500 shrink-0">Тулз:</span>
            <code className="text-amber-400/80">{tool.name}</code>
          </div>
          {tool.payload?.args != null && (
            <div>
              <span className="text-void-500">Аргументы:</span>
              <pre className="mt-0.5 bg-void-950 rounded px-2 py-1 overflow-x-auto text-[10px] text-void-300">
                {JSON.stringify(toolArgs(tool.payload.args), null, 2)}
              </pre>
            </div>
          )}
          {tool.result && (
            <div>
              <span className="text-void-500">Результат:</span>
              <pre className="mt-0.5 bg-void-950 rounded px-2 py-1 overflow-x-auto text-[10px] text-void-300">
                {JSON.stringify(tool.result, null, 2)}
              </pre>
            </div>
          )}
          {tool.error && (
            <div className="flex items-start gap-2">
              <XCircle className="h-3 w-3 text-crimson-400 mt-0.5 shrink-0" />
              <span className="text-crimson-300">{tool.error}</span>
            </div>
          )}
          <div className="text-[10px] text-void-600 pt-0.5">
            {formatTimeSafe(tool.created_at, 'HH:mm:ss')}
          </div>
        </div>
      )}
    </div>
  );
}

export function ChatBubble({ turn }: { turn: ConversationTurn }) {
  const time = formatTimeSafe(turn.timestamp, 'HH:mm');

  // Tools-only turn
  if (turn.direction === 'tools') {
    return (
      <div className="flex justify-center mb-2">
        <div className="max-w-[70%] sm:max-w-[60%] w-full space-y-1">
          {turn.tools.map((tool) => (
            <ToolCard key={tool.id} tool={tool} />
          ))}
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
            <MessageText text={turn.incoming} />
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
            <MessageText text={turn.outgoing} />
          </div>
          <div className="text-[10px] text-void-600 text-right mt-0.5">{time}</div>
        </div>
      </div>
    );
  }

  // Both: incoming + tools + outgoing
  return (
    <div className="space-y-2 mb-4">
      {/* Incoming */}
      <div className="flex justify-start">
        <div className="max-w-[85%] sm:max-w-[70%]">
          <div className="text-[11px] text-void-500 mb-0.5 truncate">{turn.peer_name || turn.peer_id}</div>
          <div className="bg-void-800 text-void-100 rounded-2xl rounded-tl-md px-4 py-2 text-sm break-words">
            <MessageText text={turn.incoming} />
          </div>
        </div>
      </div>

      {/* Tool calls */}
      {turn.tools.length > 0 && (
        <div className="flex justify-center">
          <div className="max-w-[70%] sm:max-w-[60%] w-full space-y-1">
            {turn.tools.map((tool) => (
              <ToolCard key={tool.id} tool={tool} />
            ))}
          </div>
        </div>
      )}

      {/* Outgoing */}
      <div className="flex justify-end">
        <div className="max-w-[85%] sm:max-w-[70%]">
          <div className="text-[11px] text-void-500 mb-0.5 text-right truncate">{turn.agent_name || 'Агент'}</div>
          <div className="bg-plasma-950 text-plasma-100 rounded-2xl rounded-tr-md px-4 py-2 text-sm border border-plasma-900/40 break-words">
            <MessageText text={turn.outgoing} />
          </div>
          <div className="text-[10px] text-void-600 text-right mt-0.5">{time}</div>
        </div>
      </div>
    </div>
  );
}
