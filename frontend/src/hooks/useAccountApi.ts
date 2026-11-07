'use client';

import { useMemo } from 'react';
import { createAccountApi } from '@/lib/api';
import { useAccount } from '@/hooks/useAccount';

export function useAccountApi() {
  const account = useAccount();
  return useMemo(
    () => createAccountApi(
      account
        ? { userId: account.userId, signal: account.controller.signal }
        : undefined,
    ),
    [account],
  );
}
