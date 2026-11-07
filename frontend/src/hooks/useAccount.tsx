'use client';

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { usePathname } from 'next/navigation';
import { createQueryClient, queryKeys } from '@/lib/queryClient';
import { setApiAccountScope } from '@/lib/api';
import { getSupabaseClient } from '@/lib/supabase/client';

interface AccountScope {
  userId: string | null;
  generation: number;
  queryClient: QueryClient;
  controller: AbortController;
}

type AccountState =
  | { status: 'pending' | 'error' }
  | { status: 'ready'; scope: AccountScope };

export const AccountContext = createContext<AccountScope | null>(null);

export function useAccount() {
  return useContext(AccountContext);
}

export function useAccountQueryKeys() {
  const userId = useAccount()?.userId ?? null;
  return useMemo(() => queryKeys.forUser(userId), [userId]);
}

export function AccountProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AccountState>({ status: 'pending' });
  const [publicQueryClient] = useState(() => createQueryClient());
  const current = useRef<AccountScope | null>(null);
  const generation = useRef(0);
  const pathname = usePathname();
  const publicPage = ['/login', '/register', '/reset-password', '/update-password'].includes(pathname);

  useEffect(() => {
    setState({ status: 'pending' });
    let active = true;
    let sequence = 0;
    const retire = () => {
      const outgoing = current.current;
      current.current = null;
      setApiAccountScope(undefined);
      if (!outgoing) return;
      outgoing.controller.abort();
      void outgoing.queryClient.cancelQueries();
      outgoing.queryClient.clear();
    };
    const accept = (userId: string | null) => {
      if (!active || current.current?.userId === userId) return;
      retire();
      const next: AccountScope = {
        userId,
        generation: ++generation.current,
        queryClient: createQueryClient(),
        controller: new AbortController(),
      };
      current.current = next;
      setApiAccountScope({ userId, signal: next.controller.signal });
      setState({ status: 'ready', scope: next });
      try {
        sessionStorage.removeItem('_m42_tc_state');
      } catch {
        // Storage may be unavailable.
      }
    };
    const fail = () => {
      if (!active) return;
      retire();
      setState({ status: 'error' });
    };
    let unsubscribe = () => {};
    try {
      const supabase = getSupabaseClient();
      const initialSequence = sequence;
      const {
        data: { subscription },
      } = supabase.auth.onAuthStateChange((_event, session) => {
        if (!active) return;
        sequence += 1;
        accept(session?.user.id ?? null);
      });
      unsubscribe = () => subscription.unsubscribe();
      void supabase.auth
        .getSession()
        .then(({ data, error: authError }) => {
          if (!active || sequence !== initialSequence) return;
          if (authError) fail();
          else accept(data.session?.user.id ?? null);
        })
        .catch(() => {
          if (sequence === initialSequence) fail();
        });
    } catch {
      fail();
    }
    return () => {
      active = false;
      unsubscribe();
      retire();
    };
  }, []);

  const scope = state.status === 'ready' ? state.scope : null;
  if ((!scope || scope.userId === null) && !publicPage) {
    return (
      <div role={state.status === 'error' ? 'alert' : 'status'}>
        {state.status === 'error'
          ? 'Не удалось проверить сессию. Обновите страницу.'
          : 'Проверка сессии…'}
      </div>
    );
  }

  return (
    <AccountContext.Provider key={scope?.generation ?? 'public'} value={scope}>
      <QueryClientProvider client={scope?.queryClient ?? publicQueryClient}>
        {children}
      </QueryClientProvider>
    </AccountContext.Provider>
  );
}
