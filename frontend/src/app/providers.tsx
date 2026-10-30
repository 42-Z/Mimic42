'use client';

import { useState, useEffect } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { createQueryClient } from '@/lib/queryClient';
import { AdminAccessProvider } from '@/hooks/useAdminAccess';
import { ToastProvider } from '@/components/ui/toast';
import { preloadSanitizer } from '@/lib/sanitize';

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => createQueryClient());

  useEffect(() => {
    preloadSanitizer();
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <AdminAccessProvider>
        <ToastProvider>{children}</ToastProvider>
      </AdminAccessProvider>
      {process.env.NODE_ENV === 'development' && (
        <ReactQueryDevtools initialIsOpen={false} />
      )}
    </QueryClientProvider>
  );
}
