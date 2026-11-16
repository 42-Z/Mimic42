import { afterEach, describe, expect, mock, spyOn, test } from 'bun:test';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AttackDetailPage from '@/app/(dashboard)/attacks/[id]/page';
import { ToastProvider } from '@/components/ui/toast';
import * as attackMediaHooks from '@/hooks/useAttackMedia';
import * as attacksHooks from '@/hooks/useAttacks';
import type { AttackAgentAvailability, AttackDetail } from '@/types';
import { navigationMock } from './next-navigation-mock';
import {
  ACTIVE_ATTACK_ID,
  MIMIC_A_ID,
  makeAgent,
  makeArchive,
  makeAttack,
} from './attack-fixtures';

const restores: Array<() => void> = [];

afterEach(() => {
  while (restores.length > 0) restores.pop()?.();
});

function mutation() {
  const mutate = mock((..._args: unknown[]) => {});
  return { mutate, isPending: false, variables: undefined, mutateAsync: async () => undefined };
}

function query<T>(data: T) {
  return {
    data,
    isLoading: false,
    isError: false,
    error: null,
    refetch: mock(async () => ({ data })),
  } as never;
}

function mockDetail(
  attack: AttackDetail,
  available: AttackAgentAvailability[] = [],
) {
  const attackQuery = spyOn(attacksHooks, 'useAttack').mockReturnValue(query(attack));
  const agentsQuery = spyOn(attacksHooks, 'useAttackAgents').mockReturnValue(query(available));
  const start = mutation();
  const cancel = mutation();
  const repeat = mutation();
  const update = mutation();
  const add = mutation();
  const remove = mutation();

  const hooks = [
    spyOn(attacksHooks, 'useStartAttack').mockReturnValue(start as never),
    spyOn(attacksHooks, 'useCancelAttack').mockReturnValue(cancel as never),
    spyOn(attacksHooks, 'useRepeatAttack').mockReturnValue(repeat as never),
    spyOn(attacksHooks, 'useUpdateAttack').mockReturnValue(update as never),
    spyOn(attacksHooks, 'useAddAttackAgent').mockReturnValue(add as never),
    spyOn(attacksHooks, 'useRemoveAttackAgent').mockReturnValue(remove as never),
  ];
  const media = spyOn(attackMediaHooks, 'useAttackMediaLink').mockReturnValue({
    url: 'https://signed.test/media.jpg',
    status: 'ready',
    refresh: async () => 'https://signed.test/media.jpg',
  });

  restores.push(
    () => attackQuery.mockRestore(),
    () => agentsQuery.mockRestore(),
    ...hooks.map((hook) => () => hook.mockRestore()),
    () => media.mockRestore(),
  );

  return {
    start: start.mutate,
    cancel: cancel.mutate,
    repeat: repeat.mutate,
    update: update.mutate,
    add: add.mutate,
    remove: remove.mutate,
  };
}

function renderPage() {
  return render(
    <ToastProvider>
      <AttackDetailPage />
    </ToastProvider>,
  );
}

describe('детали атаки', () => {
  test('показывает прогресс, темп, мимиков плашками и ошибки', () => {
    navigationMock.params = { id: ACTIVE_ATTACK_ID };
    mockDetail(makeAttack());
    renderPage();

    expect(screen.getByRole('heading', { level: 1, name: 'Розыгрыш' })).toBeTruthy();
    expect(screen.getByText('12 / 40 комментариев')).toBeTruthy();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('30');
    expect(screen.getByTitle('Мила: в атаке')).toBeTruthy();
    expect(screen.getByTitle('Гоша: в атаке')).toBeTruthy();
    expect(screen.getByText('Ошибки мимиков')).toBeTruthy();
    expect(screen.getByText('SlowModeWaitError: 30')).toBeTruthy();
    expect(screen.getByText('медленный режим · на мимика')).toBeTruthy();
  });

  test('удаление последнего мимика предупреждает об отмене атаки', async () => {
    navigationMock.params = { id: ACTIVE_ATTACK_ID };
    const calls = mockDetail(
      makeAttack({
        agents: [makeAgent({ name: 'Мила', agent_id: MIMIC_A_ID })],
      }),
    );
    renderPage();

    await userEvent.click(screen.getByRole('button', { name: 'Убрать мимика Мила' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Атака отменится/)).toBeTruthy();

    await userEvent.click(within(dialog).getByRole('button', { name: 'Убрать' }));
    expect(calls.remove).toHaveBeenCalledTimes(1);
    expect(calls.remove.mock.calls[0]?.[0]).toBe(MIMIC_A_ID);
  });

  test('обычное удаление мимика не требует подтверждения', async () => {
    navigationMock.params = { id: ACTIVE_ATTACK_ID };
    const calls = mockDetail(makeAttack());
    renderPage();

    await userEvent.click(screen.getByRole('button', { name: 'Убрать мимика Мила' }));

    expect(calls.remove).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('отмена идущей атаки подтверждается и вызывает API', async () => {
    navigationMock.params = { id: ACTIVE_ATTACK_ID };
    const calls = mockDetail(makeAttack());
    renderPage();

    await userEvent.click(screen.getByRole('button', { name: 'Отменить' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отменить атаку' }));

    expect(calls.cancel).toHaveBeenCalledTimes(1);
  });

  test('повтор архивной атаки вызывает API', async () => {
    navigationMock.params = { id: ACTIVE_ATTACK_ID };
    const calls = mockDetail(makeArchive());
    renderPage();

    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(calls.repeat).toHaveBeenCalledTimes(1);
  });

  test('черновик запускается кнопкой', async () => {
    navigationMock.params = { id: ACTIVE_ATTACK_ID };
    const calls = mockDetail(
      makeAttack({
        status: 'draft',
        started_at: null,
        sent_count: 0,
        claimed_count: 0,
        agents: [makeAgent({ name: 'Мила', agent_id: MIMIC_A_ID, status: 'assigned' })],
      }),
    );
    renderPage();

    await userEvent.click(screen.getByRole('button', { name: 'Запустить' }));
    expect(calls.start).toHaveBeenCalledTimes(1);
  });

  test('без мимиков запуск заблокирован с подсказкой', () => {
    navigationMock.params = { id: ACTIVE_ATTACK_ID };
    mockDetail(
      makeAttack({
        status: 'draft',
        started_at: null,
        sent_count: 0,
        claimed_count: 0,
        agents: [],
      }),
    );
    renderPage();

    expect(
      screen.getByRole('button', { name: 'Запустить' }).hasAttribute('disabled'),
    ).toBe(true);
    expect(screen.getByText('Добавьте мимика, чтобы запустить атаку.')).toBeTruthy();
  });
});
