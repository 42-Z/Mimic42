'use client';

import { useEffect } from 'react';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { AccountProvider } from '@/hooks/useAccount';
import { AdminAccessProvider } from '@/hooks/useAdminAccess';
import { ToastProvider } from '@/components/ui/toast';
import { preloadSanitizer } from '@/lib/sanitize';

export function Providers({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    preloadSanitizer();
  }, []);

  return (
    <AccountProvider>
      <AdminAccessProvider>
        <ToastProvider>{children}</ToastProvider>
      </AdminAccessProvider>
      {process.env.NODE_ENV === 'development' && (
        <ReactQueryDevtools initialIsOpen={false} />
      )}
    </AccountProvider>
  );
}
