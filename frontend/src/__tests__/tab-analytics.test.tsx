import { afterEach, expect, spyOn, test } from 'bun:test';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import * as telegramHooks from '@/hooks/useTelegramSession';
import { TabAnalytics } from '@/components/agent/TabAnalytics';

type AnalyticsData = NonNullable<ReturnType<typeof telegramHooks.useAnalyticsData>['data']>;

afterEach(() => cleanup());

test('ошибка аналитики скрывает графики и позволяет повторить загрузку', async () => {
  let attempts = 0;
  const analytics = spyOn(telegramHooks, 'useAnalyticsData').mockImplementation(() =>
    useQuery<AnalyticsData>({
      queryKey: ['analytics-error'],
      queryFn: async () => {
        attempts += 1;
        throw new Error('private database error');
      },
      retry: false,
    }),
  );
  const tokens = spyOn(telegramHooks, 'useTokenUsage').mockImplementation(() =>
    useQuery({
      queryKey: ['analytics-test-tokens'],
      queryFn: async () => ({ input_tokens: 0, output_tokens: 0 }),
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });

  try {
    render(
      <QueryClientProvider client={client}>
        <TabAnalytics agentId="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" />
      </QueryClientProvider>,
    );

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Не удалось загрузить статистику');
    expect(alert.textContent).not.toContain('private database error');
    expect(screen.queryByText('Активность по дням')).toBeNull();
    expect(screen.queryByText('Ошибки по дням')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(attempts).toBe(2));
    expect(await screen.findByRole('alert')).toBeTruthy();
  } finally {
    cleanup();
    client.clear();
    analytics.mockRestore();
    tokens.mockRestore();
  }
});
