'use client';

import { useState, type CSSProperties } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AgentStatusBadge } from '@/components/agents/AgentStatusBadge';
import { Button } from '@/components/ui/button';
import { Card, Skeleton } from '@/components/ui/card';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useAdminStatistics } from '@/hooks/useAdmin';
import type { AgentState } from '@/types';
import type { AdminStatistics as AdminStatisticsData } from '@/types/admin';

const STATE_ORDER: AgentState[] = ['running', 'starting', 'stopping', 'stopped', 'draft', 'error'];
const STATE_LABELS: Record<AgentState, string> = {
  running: 'Активен',
  starting: 'Запуск',
  stopping: 'Остановка',
  stopped: 'Остановлен',
  draft: 'Черновик',
  error: 'Ошибка',
};
const STATE_COLORS: Record<AgentState, string> = {
  running: 'rgb(var(--success))',
  starting: 'rgb(var(--primary))',
  stopping: 'rgb(var(--warning))',
  stopped: 'rgb(var(--muted-foreground) / 0.55)',
  draft: 'rgb(var(--muted-foreground) / 0.28)',
  error: 'rgb(var(--destructive))',
};
const NUMBER_FORMAT = new Intl.NumberFormat('ru-RU');
const TOOLTIP_STYLE: CSSProperties = {
  backgroundColor: 'rgb(var(--popover))',
  border: '1px solid rgb(var(--border) / 0.7)',
  borderRadius: '2px',
  color: 'rgb(var(--popover-foreground))',
  fontFamily: 'var(--font-geist-mono)',
  fontSize: '12px',
};
const TICK_STYLE = {
  fill: 'rgb(var(--muted-foreground))',
  fontFamily: 'var(--font-geist-mono)',
  fontSize: 10,
};

function formatCount(value: number): string {
  return NUMBER_FORMAT.format(value);
}

function plural(value: number, forms: [one: string, few: string, many: string]): string {
  const abs = Math.abs(value) % 100;
  if (abs > 10 && abs < 20) return forms[2];
  const last = abs % 10;
  if (last === 1) return forms[0];
  if (last >= 2 && last <= 4) return forms[1];
  return forms[2];
}

function counted(value: number, forms: [one: string, few: string, many: string]): string {
  return `${formatCount(value)} ${plural(value, forms)}`;
}

function parseUtcDate(value: string): Date {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? new Date(0) : date;
}

function formatUtcDate(value: string, withTime = false): string {
  const date = parseUtcDate(value);
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}),
    timeZone: 'UTC',
  }).format(date);
}

function formatDay(value: string): string {
  const date = parseUtcDate(`${value}T00:00:00Z`);
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(date);
}

function StateDistribution({
  states,
  total,
}: {
  states: Partial<Record<AgentState, number>>;
  total: number;
}) {
  const populated = STATE_ORDER.flatMap((state) => {
    // eslint-disable-next-line security/detect-object-injection -- key is typed AgentState union, not user input
    const count = states[state] ?? 0;
    // eslint-disable-next-line security/detect-object-injection -- key is typed AgentState union, not user input
    return count > 0 ? [{ state, count, label: STATE_LABELS[state] }] : [];
  });

  if (populated.length === 0) {
    return <p className="text-sm text-muted-foreground">Мимиков пока нет.</p>;
  }

  const single = populated.length === 1 ? populated[0] : null;

  return (
    <div className="flex flex-col items-center justify-center gap-5 sm:flex-row">
      <div
        aria-hidden="true"
        className="relative h-52 w-full max-w-52 shrink-0"
        data-testid="states-chart"
      >
        {single ? (
          <div
            aria-hidden="true"
            className="absolute inset-2 rounded-full border-[30px]"
            // eslint-disable-next-line security/detect-object-injection -- key is typed AgentState union, not user input
            style={{ borderColor: STATE_COLORS[single.state] }}
          />
        ) : (
          <ResponsiveContainer height="100%" width="100%">
            <PieChart>
              <Pie
                data={populated}
                dataKey="count"
                innerRadius="62%"
                isAnimationActive={false}
                nameKey="label"
                outerRadius="92%"
                paddingAngle={2}
                stroke="none"
              >
                {populated.map(({ state }) => {
                  // eslint-disable-next-line security/detect-object-injection -- key is typed AgentState union, not user input
                  return <Cell fill={STATE_COLORS[state]} key={state} />;
                })}
              </Pie>
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(value) => formatCount(Number(value))}
              />
            </PieChart>
          </ResponsiveContainer>
        )}
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span
            className="font-display text-2xl font-semibold tabular-nums text-foreground"
            data-testid="stat-agents"
          >
            {formatCount(total)}
          </span>
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            мимиков
          </span>
        </div>
      </div>

      <ul
        aria-label="Распределение мимиков по состояниям"
        className="flex w-full min-w-0 max-w-48 flex-col gap-2"
      >
        {populated.map(({ state, count, label }) => (
          <li
            aria-label={`${label}: ${formatCount(count)}`}
            className="flex items-center justify-between gap-3 border-b border-border/50 pb-1.5 last:border-0 last:pb-0"
            key={state}
          >
            <AgentStatusBadge size="sm" state={state} />
            <span className="font-mono text-xs tabular-nums text-foreground">
              {formatCount(count)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatisticsSkeleton() {
  return (
    <div aria-label="Загружаем статистику" aria-busy="true" className="space-y-6" role="status">
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <Skeleton className="h-80" />
        <Skeleton className="h-80" />
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <Skeleton className="h-80" />
        <Skeleton className="h-80" />
      </div>
    </div>
  );
}

export function AdminStatistics() {
  const [days, setDays] = useState<7 | 30>(7);
  const statisticsQuery = useAdminStatistics(days);
  const data = statisticsQuery.data;

  return (
    <section aria-labelledby="admin-statistics-title" className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1">
          <h2
            className="font-display text-xl font-semibold tracking-tight text-foreground"
            id="admin-statistics-title"
          >
            Общая статистика
          </h2>
          <p className="text-sm text-muted-foreground">
            Текущие показатели платформы и агрегаты активности.
          </p>
        </div>
        <ToggleGroup
          aria-label="Период статистики"
          onValueChange={(value) => {
            if (value === '7' || value === '30') setDays(Number(value) as 7 | 30);
          }}
          type="single"
          value={String(days)}
          variant="outline"
          size="sm"
          spacing={0}
        >
          <ToggleGroupItem value="7">7 дней</ToggleGroupItem>
          <ToggleGroupItem value="30">30 дней</ToggleGroupItem>
        </ToggleGroup>
      </header>

      {statisticsQuery.isLoading ? (
        <StatisticsSkeleton />
      ) : statisticsQuery.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Не удалось загрузить статистику</AlertTitle>
          <AlertDescription>Данные платформы временно недоступны. Повторите запрос.</AlertDescription>
          <Button
            className="mt-4"
            onClick={() => void statisticsQuery.refetch()}
            size="sm"
            variant="outline"
          >
            Повторить
          </Button>
        </Alert>
      ) : data ? (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
            <p className="font-mono text-xs text-muted-foreground" data-testid="utc-range">
              UTC · {formatUtcDate(data.since)} — {formatUtcDate(data.until, true)}
            </p>
            <p className="font-mono text-xs text-warning" data-testid="current-day-note">
              Текущий день неполный
            </p>
          </div>

          <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <Card className="min-w-0" padding="md">
              <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-mono text-sm font-medium text-foreground">Мимики по состояниям</h3>
                <span className="font-mono text-xs text-muted-foreground">Сейчас</span>
              </div>
              <StateDistribution states={data.states} total={data.agents} />
            </Card>

            <Card className="flex min-w-0 flex-col" padding="md">
              <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-mono text-sm font-medium text-foreground">Токены за всё время</h3>
                <span className="font-mono text-xs text-muted-foreground">Не зависят от периода</span>
              </div>
              <div className="flex flex-1 items-center">
                <div className="grid w-full gap-6 sm:grid-cols-2">
                  <div>
                    <p className="font-mono text-xs text-muted-foreground">Входные</p>
                    <p className="mt-1 font-display text-2xl font-semibold tabular-nums text-primary" data-testid="stat-input-tokens">
                      {formatCount(data.input_tokens)}
                    </p>
                  </div>
                  <div>
                    <p className="font-mono text-xs text-muted-foreground">Выходные</p>
                    <p className="mt-1 font-display text-2xl font-semibold tabular-nums text-success" data-testid="stat-output-tokens">
                      {formatCount(data.output_tokens)}
                    </p>
                  </div>
                </div>
              </div>
            </Card>
          </div>

          <div className="grid min-w-0 gap-5 xl:grid-cols-2">
            <DailyActivityChart data={data.daily} days={days} />
            <DailyErrorsChart data={data.daily} days={days} />
          </div>
        </div>
      ) : null}
    </section>
  );
}

function DailyActivityChart({
  data,
  days,
}: {
  data: AdminStatisticsData['daily'];
  days: 7 | 30;
}) {
  const summaryId = `admin-activity-summary-${days}`;
  const summary = data
    .map(
      (day) =>
        `${formatUtcDate(`${day.date}T00:00:00Z`)}: ` +
        `${counted(day.messages, ['сообщение', 'сообщения', 'сообщений'])}, ` +
        `${counted(day.actions, ['действие', 'действия', 'действий'])}`,
    )
    .join('; ');

  return (
    <Card className="min-w-0" padding="md">
      <figure aria-describedby={summaryId} aria-labelledby={`admin-activity-title-${days}`} className="min-w-0">
        <figcaption className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="font-mono text-sm font-medium text-foreground" id={`admin-activity-title-${days}`}>
            Сообщения и действия по дням
          </h3>
          <span className="font-mono text-xs text-muted-foreground">{days} дней · UTC</span>
        </figcaption>
        <p className="mb-3 text-xs text-muted-foreground" id={summaryId}>
          За период:{' '}
          {counted(
            data.reduce((total, day) => total + day.messages, 0),
            ['сообщение', 'сообщения', 'сообщений'],
          )}{' '}
          и{' '}
          {counted(
            data.reduce((total, day) => total + day.actions, 0),
            ['действие', 'действия', 'действий'],
          )}
          .
        </p>
        {data.length === 0 ? (
          <p className="text-sm text-muted-foreground">Нет данных за выбранный период.</p>
        ) : (
          <div aria-hidden="true" className="h-64 min-w-0" data-testid="activity-chart">
            <ResponsiveContainer height="100%" width="100%">
              <AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke="rgb(var(--border) / 0.45)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  interval={days === 7 ? 0 : 'preserveStartEnd'}
                  tick={TICK_STYLE}
                  tickFormatter={formatDay}
                />
                <YAxis allowDecimals={false} tick={TICK_STYLE} width={40} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  labelFormatter={(value) => formatUtcDate(`${String(value)}T00:00:00Z`)}
                />
                <Legend wrapperStyle={{ color: 'rgb(var(--muted-foreground))', fontFamily: 'var(--font-geist-mono)', fontSize: 11 }} />
                <Area
                  dataKey="messages"
                  fill="rgb(var(--primary) / 0.16)"
                  isAnimationActive={false}
                  name="Сообщения"
                  stroke="rgb(var(--primary))"
                  strokeWidth={2}
                  type="monotone"
                />
                <Area
                  dataKey="actions"
                  fill="rgb(var(--success) / 0.12)"
                  isAnimationActive={false}
                  name="Действия"
                  stroke="rgb(var(--success))"
                  strokeWidth={2}
                  type="monotone"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
        <p
          aria-label="Текстовая сводка активности по дням"
          className="sr-only"
          data-testid="activity-text-summary"
          role="note"
        >
          {summary}
        </p>
        <details className="mt-3 border-t border-border pt-3">
          <summary className="cursor-pointer font-mono text-xs text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            Данные по дням таблицей
          </summary>
          <div className="mt-3 max-h-48 overflow-y-auto">
            <table className="w-full text-left font-mono text-xs">
              <caption className="sr-only">Сообщения и действия по дням в UTC</caption>
              <thead>
                <tr>
                  <th className="py-1 pr-3 font-medium text-muted-foreground" scope="col">Дата UTC</th>
                  <th className="py-1 pr-3 font-medium text-muted-foreground" scope="col">Сообщения</th>
                  <th className="py-1 font-medium text-muted-foreground" scope="col">Действия</th>
                </tr>
              </thead>
              <tbody>
                {data.map((day) => (
                  <tr className="border-t border-border/60" key={day.date}>
                    <th className="py-1 pr-3 font-normal text-foreground" scope="row">{formatUtcDate(`${day.date}T00:00:00Z`)}</th>
                    <td className="py-1 pr-3 tabular-nums text-foreground">{formatCount(day.messages)}</td>
                    <td className="py-1 tabular-nums text-foreground">{formatCount(day.actions)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </figure>
    </Card>
  );
}

function DailyErrorsChart({
  data,
  days,
}: {
  data: AdminStatisticsData['daily'];
  days: 7 | 30;
}) {
  const totalErrors = data.reduce((total, day) => total + day.errors, 0);
  return (
    <Card className="min-w-0" padding="md">
      <figure
        aria-describedby={`admin-errors-summary-${days}`}
        aria-labelledby={`admin-errors-title-${days}`}
        className="min-w-0"
      >
        <figcaption className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="font-mono text-sm font-medium text-foreground" id={`admin-errors-title-${days}`}>
            Ошибки по дням
          </h3>
          <span className="font-mono text-xs text-muted-foreground">{days} дней · UTC</span>
        </figcaption>
        <p className="mb-3 text-xs text-muted-foreground">
          За период: {counted(totalErrors, ['ошибка', 'ошибки', 'ошибок'])}.
        </p>
        {data.length === 0 ? (
          <p className="text-sm text-muted-foreground">Нет данных за выбранный период.</p>
        ) : (
          <div aria-hidden="true" className="h-64 min-w-0" data-testid="errors-chart">
            <ResponsiveContainer height="100%" width="100%">
              <BarChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke="rgb(var(--border) / 0.45)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  interval={days === 7 ? 0 : 'preserveStartEnd'}
                  tick={TICK_STYLE}
                  tickFormatter={formatDay}
                />
                <YAxis allowDecimals={false} tick={TICK_STYLE} width={40} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  labelFormatter={(value) => formatUtcDate(`${String(value)}T00:00:00Z`)}
                />
                <Bar
                  dataKey="errors"
                  fill="rgb(var(--destructive))"
                  isAnimationActive={false}
                  name="Ошибки"
                  radius={[2, 2, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        <p className="sr-only" data-testid="errors-text-summary" id={`admin-errors-summary-${days}`}>
          {data
            .map(
              (day) =>
                `${formatUtcDate(`${day.date}T00:00:00Z`)}: ` +
                counted(day.errors, ['ошибка', 'ошибки', 'ошибок']),
            )
            .join('; ')}
        </p>
      </figure>
    </Card>
  );
}
