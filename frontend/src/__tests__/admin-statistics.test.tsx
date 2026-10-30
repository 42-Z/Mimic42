import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createElement, type ReactNode } from 'react';
import { AdminAccessContext, type AdminAccess } from '@/hooks/useAdminAccess';
import { adminApi } from '@/lib/adminApi';
import { queryKeys } from '@/lib/queryClient';
import type { AdminStatistics } from '@/types/admin';

const adminId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const access: AdminAccess = {
  userId: adminId,
  isLoading: false,
  isAdmin: true,
  isDenied: false,
  error: null,
  retry: () => undefined,
};

function statistics(days: 7 | 30, overrides: Partial<AdminStatistics> = {}): AdminStatistics {
  const until = '2026-10-19T12:00:00Z';
  const since = days === 7 ? '2026-10-13T00:00:00Z' : '2026-09-20T00:00:00Z';
  const daily = Array.from({ length: days }, (_, index) => ({
    date: new Date(Date.parse(since) + index * 86_400_000).toISOString().slice(0, 10),
    messages: index === days - 1 ? days : 0,
    actions: index === days - 1 ? Math.floor(days / 2) : 0,
    errors: 0,
  }));
  return {
    users: 4,
    agents: 3,
    states: { running: 1, stopped: 2 },
    input_tokens: 1200,
    output_tokens: 340,
    period_days: days,
    since,
    until,
    totals: { messages: days, actions: Math.floor(days / 2), errors: 0 },
    daily,
    ...overrides,
  };
}

const originalStatistics = adminApi.statistics;
let calls: Array<7 | 30>;
let loadStatistics: (days: 7 | 30) => Promise<AdminStatistics>;

function ChartWrapper({ children }: { children?: ReactNode }) {
  return createElement('div', null, children);
}

function ChartElement() {
  return null;
}

mock.module('recharts', () => ({
  Area: ChartElement,
  AreaChart: ChartWrapper,
  Bar: ChartElement,
  BarChart: ChartWrapper,
  CartesianGrid: ChartElement,
  Cell: ChartElement,
  Legend: ChartElement,
  Pie: ChartElement,
  PieChart: ChartWrapper,
  ResponsiveContainer: ChartWrapper,
  Tooltip: ChartElement,
  XAxis: ChartElement,
  YAxis: ChartElement,
}));

function renderStatistics() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <AdminAccessContext.Provider value={access}>
        <AdminStatistics />
      </AdminAccessContext.Provider>
    </QueryClientProvider>,
  );
  return { queryClient, ...view };
}

beforeEach(() => {
  calls = [];
  loadStatistics = async (days) => statistics(days);
  adminApi.statistics = async (days) => {
    calls.push(days);
    return loadStatistics(days);
  };
});

afterEach(() => {
  cleanup();
  adminApi.statistics = originalStatistics;
});

afterAll(() => mock.restore());

const { AdminStatistics } = await import('@/components/admin/AdminStatistics');

describe('AdminStatistics', () => {
  test('period selection changes the user-scoped query and ignores an empty single-toggle value', async () => {
    const { queryClient } = renderStatistics();
    expect(await screen.findByTestId('states-chart')).toBeTruthy();
    expect(screen.getByTestId('stat-agents').textContent).toBe('3');
    expect(screen.getByLabelText('Распределение мимиков по состояниям')).toBeTruthy();
    expect(calls).toEqual([7]);
    expect(
      queryClient.getQueryData<AdminStatistics>(queryKeys.admin.statistics(adminId, 7))?.period_days,
    ).toBe(7);

    fireEvent.click(screen.getByRole('radio', { name: '30 дней' }));
    expect((await screen.findByText(/За период: 30 сообщений/)).textContent).toContain('30');
    await waitFor(() => expect(calls).toEqual([7, 30]));
    expect(
      queryClient.getQueryData<AdminStatistics>(queryKeys.admin.statistics(adminId, 30))?.period_days,
    ).toBe(30);

    fireEvent.click(screen.getByRole('radio', { name: '30 дней' }));
    expect(await screen.findByText('Текущий день неполный')).toBeTruthy();
    expect(calls).toEqual([7, 30]);
  });

  test('labels lifetime tokens and the UTC window, including the incomplete current day', async () => {
    renderStatistics();

    expect(await screen.findByText('Токены за всё время')).toBeTruthy();
    expect(screen.getByTestId('stat-input-tokens').textContent?.replace(/\s/g, '')).toBe('1200');
    expect(screen.getByTestId('stat-output-tokens').textContent).toBe('340');
    expect(screen.queryByText('Всего')).toBeNull();
    expect(screen.getByTestId('utc-range').textContent).toContain('UTC');
    expect(screen.getByText('Текущий день неполный')).toBeTruthy();
    expect(screen.getByLabelText('Текстовая сводка активности по дням')).toBeTruthy();
  });

  test('shows zero only for a successful zero-valued response', async () => {
    loadStatistics = async (days) =>
      statistics(days, {
        users: 0,
        agents: 0,
        states: {},
        input_tokens: 0,
        output_tokens: 0,
        totals: { messages: 0, actions: 0, errors: 0 },
        daily: statistics(days).daily.map((day) => ({ ...day, messages: 0, actions: 0, errors: 0 })),
      });
    renderStatistics();
    expect(await screen.findByText('Мимиков пока нет.')).toBeTruthy();
    expect(screen.getByTestId('stat-input-tokens').textContent).toBe('0');
    expect(screen.getByTestId('stat-output-tokens').textContent).toBe('0');
    expect(screen.getByText(/За период: 0 ошибок/)).toBeTruthy();
  });

  test('does not convert a failed statistics response into zeros or an empty chart', async () => {
    loadStatistics = async () => {
      throw new Error('private statistics failure');
    };
    renderStatistics();

    expect((await screen.findByRole('alert')).textContent).toContain('Не удалось загрузить статистику');
    expect(screen.queryByTestId('states-chart')).toBeNull();
    expect(screen.queryByTestId('activity-chart')).toBeNull();
    expect(screen.getByRole('alert').textContent).not.toContain('private statistics failure');
  });
});
