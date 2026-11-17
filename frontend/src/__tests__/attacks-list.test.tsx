import { afterEach, describe, expect, mock, spyOn, test } from 'bun:test';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AttacksPage from '@/app/(dashboard)/attacks/page';
import { ToastProvider } from '@/components/ui/toast';
import * as attackMediaHooks from '@/hooks/useAttackMedia';
import * as attacksHooks from '@/hooks/useAttacks';
import type { AttackListResponse } from '@/lib/api';
import { makeArchive, makeAttack } from './attack-fixtures';

const restores: Array<() => void> = [];

afterEach(() => {
  while (restores.length > 0) restores.pop()?.();
});

function listQuery(
  data: AttackListResponse | null,
  options: { isError?: boolean; error?: unknown } = {},
) {
  return {
    data: data ?? undefined,
    isLoading: false,
    isError: options.isError ?? false,
    error: options.error ?? null,
    refetch: mock(async () => ({ data: data ?? undefined })),
  } as unknown as ReturnType<typeof attacksHooks.useAttacks>;
}

function mutation<TVariables>() {
  const mutate = mock((_variables: TVariables, _options?: unknown) => {});
  return {
    mutate,
    isPending: false,
    variables: undefined,
    mock: { mutate },
  };
}

function mockList(
  data: AttackListResponse | null,
  options: { isError?: boolean; error?: unknown } = {},
) {
  const query = spyOn(attacksHooks, 'useAttacks').mockReturnValue(listQuery(data, options));
  const cancel = mutation<void>();
  const repeat = mutation<void>();
  const cancelHook = spyOn(attacksHooks, 'useCancelAttack').mockReturnValue(cancel as never);
  const repeatHook = spyOn(attacksHooks, 'useRepeatAttack').mockReturnValue(repeat as never);
  const mediaHook = spyOn(attackMediaHooks, 'useAttackMediaLink').mockReturnValue({
    url: 'https://signed.test/media.jpg',
    status: 'ready',
    refresh: async () => 'https://signed.test/media.jpg',
  });

  restores.push(
    () => query.mockRestore(),
    () => cancelHook.mockRestore(),
    () => repeatHook.mockRestore(),
    () => mediaHook.mockRestore(),
  );

  return { cancel: cancel.mock.mutate, repeat: repeat.mock.mutate };
}

function renderPage() {
  return render(
    <ToastProvider>
      <AttacksPage />
    </ToastProvider>,
  );
}

describe('список атак', () => {
  test('активные идут выше архива, карточка показывает прогресс, мимиков и медиа', async () => {
    mockList({ active: [makeAttack()], archive: [makeArchive()] });
    renderPage();

    const cards = screen.getAllByTestId('attack-card');
    expect(cards).toHaveLength(2);

    const active = cards[0]!;
    expect(within(active).getByRole('link', { name: 'Розыгрыш' })).toBeTruthy();
    expect(within(active).getByText('12 / 40 комментариев')).toBeTruthy();
    expect(within(active).getByRole('progressbar').getAttribute('aria-valuenow')).toBe('30');
    expect(within(active).getByText(/Темп: 30 с · медленный режим/)).toBeTruthy();
    expect(within(active).getByText('Мила')).toBeTruthy();
    expect(within(active).getByTitle('Мила: в атаке')).toBeTruthy();
    expect(within(active).getAllByTitle('SlowModeWaitError: 30').length).toBeGreaterThan(0);
    expect(within(active).getByText('2 текста')).toBeTruthy();
    expect(within(active).getByAltText('a.jpg')).toBeTruthy();

    const archive = cards[1]!;
    expect(within(archive).getByRole('link', { name: 'Старая атака' })).toBeTruthy();
    expect(within(archive).getByText('20 / 20 комментариев')).toBeTruthy();
    expect(within(archive).getByRole('progressbar').getAttribute('aria-valuenow')).toBe('100');
    expect(within(archive).getByText('1 текст')).toBeTruthy();
  });

  test('отмена идущей атаки спрашивает подтверждение и вызывает API', async () => {
    const calls = mockList({ active: [makeAttack()], archive: [] });
    renderPage();

    await userEvent.click(screen.getByRole('button', { name: 'Отменить' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Отменить атаку?')).toBeTruthy();

    await userEvent.click(within(dialog).getByRole('button', { name: 'Отменить атаку' }));
    expect(calls.cancel).toHaveBeenCalledTimes(1);
  });

  test('повтор архивной атаки вызывает API', async () => {
    const calls = mockList({ active: [], archive: [makeArchive()] });
    renderPage();

    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(calls.repeat).toHaveBeenCalledTimes(1);
  });

  test('пустой список приглашает создать атаку', () => {
    mockList({ active: [], archive: [] });
    renderPage();

    expect(screen.getByText('Атак пока нет')).toBeTruthy();
    const links = screen.getAllByRole('link', { name: 'Создать атаку' });
    expect(links.length).toBeGreaterThan(0);
    expect(links[0]?.getAttribute('href')).toBe('/attacks/new');
  });

  test('ошибка загрузки не показывает внутренний текст и даёт повторить', () => {
    mockList(null, { isError: true, error: { status: 500, message: 'private database error' } });
    renderPage();

    expect(screen.getByText('Не удалось загрузить атаки')).toBeTruthy();
    expect(screen.queryByText(/private database error/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeTruthy();
  });
});
