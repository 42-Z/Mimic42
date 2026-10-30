import { AdminBoundary } from '@/components/admin/AdminBoundary';
import { AdminNavigation } from '@/components/admin/AdminNavigation';

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AdminBoundary>
      <section className="mx-auto w-full max-w-7xl space-y-6">
        <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          Администрирование
        </h1>
        <AdminNavigation />
        <div className="min-w-0">{children}</div>
      </section>
    </AdminBoundary>
  );
}
