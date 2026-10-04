import { describe, expect, test } from 'bun:test';
import { act, renderHook } from '@testing-library/react';

import { useSyncedDraft } from '@/hooks/useSyncedDraft';

function setup(initial: string | undefined, key = 'agent-1') {
  const applied: string[] = [];
  const hook = renderHook(
    ({ source, resetKey }: { source: string | undefined; resetKey: string }) =>
      useSyncedDraft(source, resetKey, (fresh) => applied.push(fresh)),
    { initialProps: { source: initial, resetKey: key } },
  );
  return { applied, hook };
}

describe('useSyncedDraft', () => {
  test('первая загрузка и обновление нетронутой формы применяются', () => {
    const { applied, hook } = setup(undefined);
    expect(applied).toEqual([]);

    hook.rerender({ source: 'v1', resetKey: 'agent-1' });
    hook.rerender({ source: 'v2', resetKey: 'agent-1' });

    expect(applied).toEqual(['v1', 'v2']);
  });

  test('фоновое обновление не затирает несохранённые правки', () => {
    const { applied, hook } = setup('v1');
    act(() => hook.result.current.setDirty(true));

    hook.rerender({ source: 'v2', resetKey: 'agent-1' });

    expect(applied).toEqual(['v1']);
    expect(hook.result.current.dirty).toBe(true);
  });

  test('после сохранения (dirty снят) следующее обновление становится базой', () => {
    const { applied, hook } = setup('v1');
    act(() => hook.result.current.setDirty(true));
    hook.rerender({ source: 'v2', resetKey: 'agent-1' });

    act(() => hook.result.current.setDirty(false));
    hook.rerender({ source: 'v3', resetKey: 'agent-1' });

    expect(applied).toEqual(['v1', 'v3']);
  });

  test('при смене агента правки отбрасываются и применяются данные нового', () => {
    const { applied, hook } = setup('a1');
    act(() => hook.result.current.setDirty(true));

    hook.rerender({ source: 'b1', resetKey: 'agent-2' });

    expect(applied).toEqual(['a1', 'b1']);
    expect(hook.result.current.dirty).toBe(false);
  });
});
