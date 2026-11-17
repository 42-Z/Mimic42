import { afterEach, describe, expect, mock, spyOn, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AttackForm } from '@/components/attacks/AttackForm';
import * as attackMediaHooks from '@/hooks/useAttackMedia';
import type { AttackEditFormState, AttackFormState } from '@/lib/attacks/types';
import type { AttackAgentAvailability, AttackDraft, AttackPatch } from '@/types';
import {
  MIMIC_A_ID,
  MIMIC_B_ID,
  MIMIC_C_ID,
  makeAvailability,
} from './attack-fixtures';

const restores: Array<() => void> = [];

afterEach(() => {
  while (restores.length > 0) restores.pop()?.();
});

const VALID: AttackFormState = {
  title: '',
  target_link: 'https://t.me/example/412',
  texts: ['Привет!'],
  images: [],
  limit_kind: 'messages',
  message_limit: 40,
  duration_minutes: null,
  agent_ids: [],
};

const EDIT_INITIAL: AttackEditFormState = {
  version: 2,
  title: 'Розыгрыш',
  texts: ['Привет!'],
  images: [],
  limit_kind: 'messages',
  message_limit: 40,
  duration_minutes: null,
};

function renderCreate(
  initial: AttackFormState = VALID,
  agents: AttackAgentAvailability[] = [],
  onCreate = mock((_draft: AttackDraft, _intent: 'draft' | 'start') => {}),
) {
  render(
    <AttackForm
      mode="create"
      initial={initial}
      agents={agents}
      onCreate={onCreate}
    />,
  );
  return onCreate;
}

function renderEdit(
  editInitial: AttackEditFormState = EDIT_INITIAL,
  sentCount = 0,
  onUpdate = mock((_patch: AttackPatch) => {}),
) {
  render(
    <AttackForm
      mode="edit"
      targetLink="https://t.me/example/412"
      editInitial={editInitial}
      sentCount={sentCount}
      onUpdate={onUpdate}
    />,
  );
  return onUpdate;
}

describe('AttackForm — длина текста', () => {
  test('без картинок текст до 4096 символов', async () => {
    const onCreate = renderCreate({ ...VALID, texts: ['x'.repeat(4097)] });

    expect(screen.getByText('Текст не длиннее 4096 символов')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));
    expect(onCreate).not.toHaveBeenCalled();
  });

  test('с картинками текст до 1024 символов', async () => {
    const media = spyOn(attackMediaHooks, 'useAttackMediaLink').mockReturnValue({
      url: 'https://signed.test/a.jpg',
      status: 'ready',
      refresh: async () => 'https://signed.test/a.jpg',
    });
    restores.push(() => media.mockRestore());

    const onCreate = renderCreate({
      ...VALID,
      images: [{ path: 'attacks/owner/uuid/a.jpg', name: 'a.jpg' }],
      texts: ['x'.repeat(1025)],
    });

    expect(screen.getByText('С картинками текст не длиннее 1024 символов')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));
    expect(onCreate).not.toHaveBeenCalled();
  });
});

describe('AttackForm — лимит', () => {
  test('задаётся ровно один лимит, переключение типа очищает прежнее поле', async () => {
    const onCreate = renderCreate();

    await userEvent.click(screen.getByText('Минуты').closest('button')!);
    const duration = screen.getByLabelText('Длительность, минуты');
    await userEvent.clear(duration);
    await userEvent.type(duration, '30');

    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));

    expect(onCreate).toHaveBeenCalledTimes(1);
    const call = onCreate.mock.calls[0]!;
    expect(call[1]).toBe('draft');
    expect(call[0].limit_kind).toBe('minutes');
    expect(call[0].duration_minutes).toBe(30);
    expect(call[0].message_limit).toBeUndefined();
  });
});

describe('AttackForm — правка', () => {
  test('ссылка на пост заблокирована', () => {
    renderEdit();

    const link = screen.getByLabelText('Ссылка на пост');
    expect(link.hasAttribute('disabled')).toBe(true);
    expect((link as HTMLInputElement).value).toBe('https://t.me/example/412');
  });

  test('подтверждение отправляет текущую версию атаки', async () => {
    const onUpdate = renderEdit();

    await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }));

    expect(onUpdate).toHaveBeenCalledTimes(1);
    const patch = onUpdate.mock.calls[0]?.[0];
    expect(patch?.version).toBe(2);
  });

  test('лимит ниже уже отправленного предупреждает о завершении', () => {
    renderEdit({ ...EDIT_INITIAL, message_limit: 10 }, 12);

    expect(screen.getByText('Лимит меньше уже отправленного')).toBeTruthy();
    expect(screen.getByText(/Отправлено 12/)).toBeTruthy();
  });

  test('лимит на уровне отправленного не предупреждает', () => {
    renderEdit({ ...EDIT_INITIAL, message_limit: 12 }, 12);

    expect(screen.queryByText('Лимит меньше уже отправленного')).toBeNull();
  });
});

describe('AttackForm — выбор мимиков', () => {
  test('выбранный мимик попадает в черновик', async () => {
    const onCreate = renderCreate(VALID, [
      makeAvailability({ agent_id: MIMIC_A_ID, name: 'Мила' }),
    ]);

    await userEvent.click(screen.getByText('Мила').closest('button')!);
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));

    expect(onCreate.mock.calls[0]?.[0].agent_ids).toEqual([MIMIC_A_ID]);
  });

  test('остановленный доступен, ограниченный заблокирован, занятый предупреждает о переносе', () => {
    const agents: AttackAgentAvailability[] = [
      makeAvailability({ agent_id: MIMIC_A_ID, name: 'Стоящий', state: 'stopped' }),
      makeAvailability({
        agent_id: MIMIC_B_ID,
        name: 'Ограниченный',
        warmup_restricted_at: '2026-11-16T10:00:00.000Z',
      }),
      makeAvailability({
        agent_id: MIMIC_C_ID,
        name: 'Занятый',
        active_attack_id: '33333333-3333-4333-8333-333333333333',
      }),
    ];

    renderCreate(VALID, agents);

    const stopped = screen.getByText('Стоящий').closest('button');
    const restricted = screen.getByText('Ограниченный').closest('button');
    expect(stopped?.hasAttribute('disabled')).toBe(false);
    expect(restricted?.hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('Остановлен — запустится вместе с атакой')).toBeTruthy();
    expect(screen.getByText('Уже в другой атаке — будет перенесён')).toBeTruthy();
    expect(screen.getByText('Telegram ограничил аккаунт: писать первым нельзя')).toBeTruthy();
  });
});
