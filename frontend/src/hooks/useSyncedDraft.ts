'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Форма, которая подхватывает свежие данные с сервера, но не затирает правки пользователя.
 *
 * Пока форма изменена (`dirty`), новые `source` игнорируются. Базовой версией форма
 * становится при первой загрузке, при смене `resetKey` (другой агент) и после того, как
 * вызывающий код снимет `dirty` (например, сразу после своего сохранения).
 */
export function useSyncedDraft<T>(
  source: T | undefined,
  resetKey: string,
  apply: (fresh: T) => void,
) {
  const [dirty, setDirtyState] = useState(false);
  const dirtyRef = useRef(false);
  const applyRef = useRef(apply);
  applyRef.current = apply;

  const setDirty = useCallback((next: boolean) => {
    dirtyRef.current = next;
    setDirtyState(next);
  }, []);

  useEffect(() => {
    dirtyRef.current = false;
    setDirtyState(false);
  }, [resetKey]);

  useEffect(() => {
    if (source !== undefined && !dirtyRef.current) applyRef.current(source);
  }, [source, resetKey]);

  return { dirty, setDirty };
}
