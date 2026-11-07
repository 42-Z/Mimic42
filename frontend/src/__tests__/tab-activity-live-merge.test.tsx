import { afterEach, describe, expect, mock, spyOn, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ActivityFeedPages } from '@/hooks/useActivityFeed';
import * as realtimeFeed from '@/hooks/useRealtimeFeed';
import { TabActivity } from '@/components/activity/TabActivity';
import type { ActivityItem } from '@/lib/activity/normalize';
import { queryKeys } from '@/lib/queryClient';
import type { ConversationTurn } from '@/types';

const AGENT_ID = '11111111-2222-4333-8444-555555555555';
const TIMESTAMP = '2026-11-07T10:00:00Z';

const history = (incoming: string): ConversationTurn => ({
  id: 'history-1',
  agent_id: AGENT_ID,
  timestamp: TIMESTAMP,
  peer_id: '123',
  peer_name: 'Алиса',
  agent_name: 'Мимик',
  incoming,
  outgoing: '',
  direction: incoming ? 'incoming' : 'tools',
  turn_id: 't1',
  incoming_media: [],
  tools: [],
});

const live = (incoming: ActivityItem['incoming']): ActivityItem => ({
  kind: 'turn',
  id: 'turn:t1',
  agentId: AGENT_ID,
  turnId: 't1',
  peer: '123',
  peerTitle: 'Алиса',
  createdAt: TIMESTAMP,
  endedAt: null,
  failed: false,
  incoming,
  response: null,
  trigger: null,
  actions: [{
    id: 'tool-1',
    eventType: 'tool.get_me',
    status: 'running',
    label: 'Информация об аккаунте',
    hint: null,
    args: { peer: '123' },
    result: null,
    startedAt: TIMESTAMP,
    completedAt: null,
    traceUrl: null,
  }],
});

function renderFeed(historical: ConversationTurn, realtime: ActivityItem) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  client.setQueryData<ActivityFeedPages>(queryKeys.conversation.byAgent(AGENT_ID), {
    pages: [{ turns: [historical], next_before: null, next_before_id: null }],
    pageParams: [null],
  });
  client.setQueryData(queryKeys.threads.byAgent(AGENT_ID), []);
  spyOn(realtimeFeed, 'useRealtimeFeed').mockReturnValue({
    items: [realtime],
    isConnected: true,
    clearFeed: () => {},
  });
  return render(
    <QueryClientProvider client={client}>
      <TabActivity agentId={AGENT_ID} />
    </QueryClientProvider>,
  );
}

afterEach(() => mock.restore());

describe('TabActivity объединяет неполную историю и текущий ход', () => {
  test('входящее видно до первого события инструмента или завершения модели', () => {
    renderFeed(history(''), {
      ...live({ id: 'incoming-1', content: 'Модель ещё думает', createdAt: TIMESTAMP }),
      actions: [],
    });

    expect(screen.getByText('Модель ещё думает')).toBeTruthy();
    expect(screen.getByText('1 записей')).toBeTruthy();
  });

  test('входящее сообщение и работающий инструмент не теряются за историей того же хода', () => {
    renderFeed(history(''), live({
      id: 'incoming-1',
      content: 'Проверь мой аккаунт',
      createdAt: TIMESTAMP,
    }));

    expect(screen.getByText('Проверь мой аккаунт')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Информация об аккаунте/ })).toBeTruthy();
    expect(screen.getByText('1 записей')).toBeTruthy();
    expect(screen.queryByText('пустой ход')).toBeNull();
  });

  test('инструмент из текущего хода не вытесняет входящее сообщение из истории', () => {
    renderFeed(history('Проверь мой аккаунт'), live(null));

    expect(screen.getByText('Проверь мой аккаунт')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Информация об аккаунте/ })).toBeTruthy();
    expect(screen.getByText('1 записей')).toBeTruthy();
  });
});
