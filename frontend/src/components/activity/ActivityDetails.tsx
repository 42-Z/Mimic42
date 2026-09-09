'use client';

import { useState } from 'react';
import { ChevronDown, Braces } from 'lucide-react';
import type { ActivityAction } from '@/lib/activity/normalize';
import { cn } from '@/lib/utils';

function valueToString(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value, null, 2);
}

function KVTable({ rows, accent }: { rows: [string, unknown][]; accent?: 'error' }) {
  if (rows.length === 0) return null;
  return (
    <div className="rounded-[2px] border border-void-800 divide-y divide-void-800/60">
      {rows.map(([key, value]) => (
        <div key={key} className="flex gap-3 px-2.5 py-1.5">
          <span className="font-mono text-[10px] text-void-600 uppercase tracking-wider w-28 shrink-0 pt-0.5">
            {key}
          </span>
          <span
            className={cn(
              'font-mono text-[11px] whitespace-pre-wrap break-words min-w-0 flex-1',
              accent === 'error' ? 'text-crimson-300' : 'text-void-300',
            )}
          >
            {valueToString(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function RawJson({ title, value }: { title: string; value: Record<string, unknown> | null }) {
  const [open, setOpen] = useState(false);
  if (!value || Object.keys(value).length === 0) return null;
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 font-mono text-[10px] text-void-600 hover:text-void-400 transition-colors"
      >
        <Braces className="h-3 w-3" />
        {title}
        <ChevronDown className={cn('h-3 w-3 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <pre className="mt-1.5 max-h-48 overflow-auto p-2 rounded-[2px] bg-void-950/60 border border-void-800 font-mono text-[10px] text-void-400 whitespace-pre-wrap break-words">
          {JSON.stringify(value, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function ActivityDetails({ action }: { action: ActivityAction }) {
  const args = action.args;
  const result = action.result;
  const argRows: [string, unknown][] = args ? Object.entries(args).filter(([k]) => k !== 'turn_id' && k !== 'peer') : [];
  const resultRows: [string, unknown][] = result
    ? Object.entries(result)
        .filter(([k]) => !['success', 'error', 'error_code'].includes(k))
        .map(([k, v]) => [k, v] as [string, unknown])
    : [];

  const hasStructured = argRows.length > 0 || resultRows.length > 0;

  return (
    <div className="mt-1 mb-2 ml-9 space-y-2">
      {action.hint && (
        <p className="font-mono text-[11px] text-crimson-400">{action.hint}</p>
      )}
      {hasStructured && (
        <>
          {argRows.length > 0 && <KVTable rows={argRows} />}
          {resultRows.length > 0 && <KVTable rows={resultRows} />}
        </>
      )}
      {!hasStructured && !action.hint && (
        <p className="font-mono text-[10px] text-void-600">Детали недоступны</p>
      )}
      <RawJson title="Аргументы JSON" value={args} />
      <RawJson title="Результат JSON" value={result} />
    </div>
  );
}
