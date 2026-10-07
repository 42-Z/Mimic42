import { afterEach, describe, expect, mock, spyOn, test } from 'bun:test';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatsSettings } from '@/components/agent/ChatsSettings';
import { agentsApi } from '@/lib/api';
import type { AgentChat } from '@/types';

const AGENT_ID = '2dbc9cfd-4860-4c43-8c95-653d5155de00';

const NEWS: AgentChat = {
  id: -1001000000001,
  title: 'Новости дня',
  username: 'daily_news',
  kind: 'channel',
  discussion_of: null,
};
const COMMENTS: AgentChat = {
  id: -1001000000002,
  title: 'Комментарии дня',
  username: null,
  kind: 'group',
  discussion_of: NEWS.id,
};
const FRIENDS: AgentChat = {
  id: -1001000000003,
  title: 'Чат друзей',
  username: null,
  kind: 'group',
  discussion_of: null,
};
const ANNA: AgentChat = { id: 42, title: 'Анна', username: null, kind: 'private', discussion_of: null };

let listChats: ReturnType<typeof spyOn> | undefined;

afterEach(() => listChats?.mockRestore());

function renderSection(value: number[], onChange: (next: number[]) => void = () => {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ChatsSettings agentId={AGENT_ID} value={value} onChange={onChange} />
    </QueryClientProvider>,
  );
  return screen.getByTestId('chats-settings');
}

function mockChats(chats: AgentChat[]) {
  listChats = spyOn(agentsApi, 'listChats').mockResolvedValue(chats);
}

describe('ChatsSettings', () => {
  test('счётчик, группы свёрнуты, раскрытие показывает чаты', async () => {
    mockChats([NEWS, FRIENDS, ANNA]);
    const user = userEvent.setup();
    const section = renderSection([]);

    expect(await within(section).findByText('Доступно 3 из 3')).toBeTruthy();
    expect(within(section).queryByRole('switch', { name: 'Новости дня' })).toBeNull();

    await user.click(within(section).getByTestId('chat-group-channel'));
    expect(within(section).getByRole('switch', { name: 'Новости дня' })).toBeTruthy();
  });

  test('выключение чата отдаёт список отключённых с его ID', async () => {
    mockChats([NEWS, ANNA]);
    const user = userEvent.setup();
    const onChange = mock((_next: number[]) => {});
    const section = renderSection([999], onChange);
    await user.click(await within(section).findByTestId('chat-group-channel'));

    await user.click(within(section).getByRole('switch', { name: 'Новости дня' }));

    expect(onChange).toHaveBeenCalledWith([999, NEWS.id]);
  });

  test('отключённые чаты показываются выключенными и считаются', async () => {
    mockChats([NEWS, ANNA]);
    const user = userEvent.setup();
    const section = renderSection([ANNA.id]);
    expect(await within(section).findByText('Доступно 1 из 2')).toBeTruthy();

    await user.click(within(section).getByTestId('chat-group-private'));
    expect(within(section).getByRole('switch', { name: 'Анна' }).getAttribute('aria-checked')).toBe(
      'false',
    );
  });

  test('переключатель группы отключает все её чаты и сохраняет чужие ID', async () => {
    mockChats([NEWS, FRIENDS, COMMENTS, ANNA]);
    const user = userEvent.setup();
    const onChange = mock((_next: number[]) => {});
    const section = renderSection([ANNA.id], onChange);
    await within(section).findByText(/Доступно/);

    await user.click(within(section).getByRole('switch', { name: 'Все чаты группы «Группы»' }));

    const [next] = onChange.mock.calls[0] as [number[]];
    expect(next).toContain(ANNA.id);
    expect(next).toContain(FRIENDS.id);
    // Группа обсуждения включённого канала заблокирована им и не трогается групповым выключением.
    expect(next).not.toContain(COMMENTS.id);
  });

  test('группа обсуждения включённого канала заблокирована с пояснением', async () => {
    mockChats([NEWS, COMMENTS]);
    const user = userEvent.setup();
    const section = renderSection([COMMENTS.id]);
    await user.click(await within(section).findByTestId('chat-group-group'));

    const comments = within(section).getByRole('switch', { name: 'Комментарии дня' });
    expect(comments.getAttribute('aria-checked')).toBe('true');
    expect((comments as HTMLButtonElement).disabled).toBe(true);
    expect(
      within(section).getByText(/Комментарии канала «Новости дня»: доступна, пока канал включён/),
    ).toBeTruthy();
  });

  test('при отключённом канале группа обсуждения переключается сама', async () => {
    mockChats([NEWS, COMMENTS]);
    const user = userEvent.setup();
    const section = renderSection([NEWS.id, COMMENTS.id]);
    await user.click(await within(section).findByTestId('chat-group-group'));

    const comments = within(section).getByRole('switch', { name: 'Комментарии дня' });
    expect(comments.getAttribute('aria-checked')).toBe('false');
    expect((comments as HTMLButtonElement).disabled).toBe(false);
  });

  test('поиск по названию и @username раскрывает группы', async () => {
    mockChats([NEWS, FRIENDS, ANNA]);
    const user = userEvent.setup();
    const section = renderSection([]);
    await within(section).findByText(/Доступно/);

    await user.type(within(section).getByLabelText('Поиск чатов'), 'daily_news');

    expect(within(section).getByRole('switch', { name: 'Новости дня' })).toBeTruthy();
    expect(within(section).queryByRole('switch', { name: 'Чат друзей' })).toBeNull();
  });

  test('«Включить все» очищает список отключённых', async () => {
    mockChats([NEWS]);
    const user = userEvent.setup();
    const onChange = mock((_next: number[]) => {});
    const section = renderSection([NEWS.id], onChange);
    await within(section).findByText(/Доступно/);

    await user.click(within(section).getByRole('button', { name: 'Включить все' }));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  test('отключённые ID вне списка диалогов показываются и включаются обратно', async () => {
    mockChats([ANNA]);
    const user = userEvent.setup();
    const onChange = mock((_next: number[]) => {});
    const section = renderSection([777, ANNA.id], onChange);
    await within(section).findByText(/Доступно/);

    expect(within(section).getByText('Нет в списке диалогов')).toBeTruthy();
    await user.click(within(section).getByRole('switch', { name: 'Чат 777' }));

    expect(onChange).toHaveBeenCalledWith([ANNA.id]);
  });

  test('длинный список показывается порциями по 100', async () => {
    const many: AgentChat[] = Array.from({ length: 130 }, (_, index) => ({
      id: 1000 + index,
      title: `Человек ${index}`,
      username: null,
      kind: 'private',
      discussion_of: null,
    }));
    mockChats(many);
    const user = userEvent.setup();
    const section = renderSection([]);
    await user.click(await within(section).findByTestId('chat-group-private'));

    expect(within(section).getAllByRole('switch', { name: /^Человек \d+$/ })).toHaveLength(100);
    await user.click(within(section).getByRole('button', { name: 'Показать ещё' }));
    expect(within(section).getAllByRole('switch', { name: /^Человек \d+$/ })).toHaveLength(130);
  });

  test('остановленный агент (409): пояснение вместо списка, отключённые ID на месте', async () => {
    listChats = spyOn(agentsApi, 'listChats').mockRejectedValue({
      status: 409,
      message: 'Агент не запущен: запустите его, чтобы увидеть чаты.',
    });
    const section = renderSection([ANNA.id]);

    expect(await within(section).findByTestId('chats-not-running')).toBeTruthy();
    expect(within(section).getByRole('switch', { name: `Чат ${ANNA.id}` })).toBeTruthy();
    expect(within(section).queryByText(/Доступно/)).toBeNull();
  });

  test('прочая ошибка показывает сообщение и «Повторить»', async () => {
    listChats = spyOn(agentsApi, 'listChats').mockRejectedValue({
      status: 502,
      message: 'Не удалось получить список чатов из Telegram.',
    });
    const section = renderSection([]);

    await waitFor(() =>
      expect(within(section).getByRole('alert').textContent).toContain('Не удалось получить'),
    );
    expect(within(section).getByRole('button', { name: 'Повторить' })).toBeTruthy();
  });
});
