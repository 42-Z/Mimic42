'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LayoutDashboard, Library, Network, Settings, Users } from 'lucide-react';
import { cn } from '@/lib/utils';

const sections = [
  { href: '/admin', label: 'Обзор', icon: LayoutDashboard },
  { href: '/admin/users', label: 'Пользователи', icon: Users },
  { href: '/admin/presets', label: 'Пресеты', icon: Library },
  { href: '/admin/proxies', label: 'Прокси', icon: Network },
  { href: '/admin/telegram', label: 'Telegram', icon: Settings },
] as const;

function isCurrentSection(pathname: string, href: string): boolean {
  if (href === '/admin') return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AdminNavigation() {
  const pathname = usePathname();

  return (
    <nav aria-label="Разделы администрирования" className="border-b border-border">
      <ul className="flex flex-wrap gap-x-1">
        {sections.map(({ href, label, icon: Icon }) => {
          const active = isCurrentSection(pathname, href);
          return (
            <li key={href}>
              <Link
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'inline-flex min-h-11 items-center gap-2 border-b-2 px-3 py-2 font-mono text-sm transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                  active
                    ? 'border-primary bg-primary/5 text-primary'
                    : 'border-transparent text-muted-foreground hover:bg-muted/50 hover:text-foreground',
                )}
                href={href}
              >
                <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
