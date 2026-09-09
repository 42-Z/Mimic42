'use client';

import { useState } from 'react';
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts';
import { useAnalyticsData } from '@/hooks/useTelegramSession';
import { Card, Skeleton } from '@/components/ui/card';
import { cn } from '@/lib/utils';

const TOOLTIP_STYLE = {
  backgroundColor: '#1a1a28',
  border: '1px solid rgba(96, 96, 117, 0.2)',
  borderRadius: '2px',
  fontFamily: 'var(--font-geist-mono)',
  fontSize: '11px',
  color: '#c0c0cc',
};

export function TabAnalytics({ agentId }: { agentId: string }) {
  const [days, setDays] = useState<7 | 30>(7);
  const { data, isLoading } = useAnalyticsData(agentId, days);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        {([7, 30] as const).map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={cn(
              'px-4 py-1.5 rounded-sm font-mono text-xs border transition-colors',
              days === d
                ? 'bg-plasma-950 border-plasma-800 text-plasma-400'
                : 'border-void-700 text-void-500 hover:text-void-300',
            )}
          >
            {d} дней
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card variant="glass" padding="md">
            <h3 className="font-mono text-xs text-void-400 uppercase tracking-wider mb-4">
              Активность по дням
            </h3>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={data}>
                <defs>
                  <linearGradient id="msgGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#1a7fff" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#1a7fff" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="actGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(96,96,117,0.1)" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fontFamily: 'Space Mono', fill: '#606075' }} />
                <YAxis tick={{ fontSize: 10, fontFamily: 'Space Mono', fill: '#606075' }} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Legend
                  wrapperStyle={{ fontSize: 10, fontFamily: 'Space Mono', color: '#606075' }}
                />
                <Area
                  type="monotone"
                  dataKey="messages"
                  name="Сообщения"
                  stroke="#1a7fff"
                  fill="url(#msgGrad)"
                  strokeWidth={1.5}
                  dot={false}
                />
                <Area
                  type="monotone"
                  dataKey="actions"
                  name="Действия"
                  stroke="#10b981"
                  fill="url(#actGrad)"
                  strokeWidth={1.5}
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </Card>

          <Card variant="glass" padding="md">
            <h3 className="font-mono text-xs text-void-400 uppercase tracking-wider mb-4">
              Ошибки по дням
            </h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(96,96,117,0.1)" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fontFamily: 'Space Mono', fill: '#606075' }} />
                <YAxis tick={{ fontSize: 10, fontFamily: 'Space Mono', fill: '#606075' }} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Bar dataKey="errors" name="Ошибки" fill="#f43f5e" opacity={0.8} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </div>
      )}
    </div>
  );
}
