'use client';

import Link from 'next/link';
import { RefreshCw, ShieldAlert } from 'lucide-react';
import { useAdminAccess, type AdminAccess } from '@/hooks/useAdminAccess';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/card';

export function AdminBoundary({ children }: { children: React.ReactNode }) {
  const access = useAdminAccess();

  return <AdminBoundaryContent access={access}>{children}</AdminBoundaryContent>;
}

export function AdminBoundaryContent({
  access,
  children,
}: {
  access: AdminAccess;
  children: React.ReactNode;
}) {
  if (access.isLoading) {
    return (
      <section
        aria-label="Проверка административного доступа"
        aria-busy="true"
        className="mx-auto w-full max-w-5xl space-y-6"
        data-testid="admin-boundary-loading"
        role="status"
      >
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-10 w-full max-w-2xl" />
        <Skeleton className="h-48 w-full" />
      </section>
    );
  }

  if (access.isDenied || (!access.isAdmin && access.error === null)) {
    return (
      <Empty className="mx-auto min-h-[50vh] max-w-xl border-0 bg-transparent">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <ShieldAlert aria-hidden="true" className="h-5 w-5 text-warning" />
          </EmptyMedia>
          <EmptyTitle aria-level={1} id="admin-denied-title" role="heading">
            Нет доступа
          </EmptyTitle>
          <EmptyDescription>
            Этот раздел доступен только администраторам.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Link
            className="rounded-sm px-3 py-2 font-mono text-sm text-primary underline underline-offset-4 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            href="/dashboard"
          >
            К своим агентам
          </Link>
        </EmptyContent>
      </Empty>
    );
  }

  if (access.error !== null) {
    return (
      <Alert className="mx-auto max-w-2xl" variant="destructive">
        <ShieldAlert aria-hidden="true" />
        <div className="min-w-0">
          <AlertTitle>Не удалось проверить доступ</AlertTitle>
          <AlertDescription>
            Административный раздел пока недоступен. Повторите проверку.
          </AlertDescription>
          <Button className="mt-4" onClick={access.retry} size="sm" variant="outline">
            <RefreshCw aria-hidden="true" className="h-4 w-4" />
            Повторить
          </Button>
        </div>
      </Alert>
    );
  }

  return <>{children}</>;
}
