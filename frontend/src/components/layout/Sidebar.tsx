'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import {
  LayoutDashboard,
  Bot,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Plus,
  Zap,
  X,
} from 'lucide-react';
import { getSupabaseClient } from '@/lib/supabase/client';
import { useRouter } from 'next/navigation';
import { useAgents } from '@/hooks/useAgents';
import { Button } from '@/components/ui/button';

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  exact?: boolean;
}

const mainNav: NavItem[] = [
  { href: '/dashboard', label: 'Главная', icon: LayoutDashboard, exact: true },
];

// Общие классы состояний навигации: фокус виден, активный пункт несёт
// индикатор слева (плазменный) и подсвеченный фон.
const navItemBase = cn(
  'flex items-center rounded-sm border-l transition-colors duration-150',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
);
const navItemState = (isActive: boolean) =>
  cn(
    isActive
      ? 'bg-primary/10 text-primary border-primary'
      : 'text-muted-foreground hover:text-foreground hover:bg-muted/60 border-transparent',
  );

interface SidebarProps {
  className?: string;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

export function Sidebar({ className, mobileOpen = false, onMobileClose }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = React.useState(false);
  const { data: agents } = useAgents();

  const handleLogout = async () => {
    const supabase = getSupabaseClient();
    await supabase.auth.signOut();
    router.push('/login');
  };

  const isActive = (href: string, exact = false) => {
    if (exact) return pathname === href;
    return pathname.startsWith(href);
  };

  return (
    <>
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={onMobileClose}
          aria-hidden="true"
        />
      )}

    <aside
      className={cn(
        'relative flex flex-col h-dvh',
        'bg-card/60 border-r border-border backdrop-blur-md',
        'transition-[width] duration-300 ease-spring',
        'md:translate-x-0',
        collapsed ? 'md:w-16' : 'md:w-64',
        // Mobile: fixed drawer
        'fixed inset-y-0 left-0 z-50 w-64 transform transition-transform duration-300 md:relative',
        mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0',
        className
      )}
    >
      {/* Top scan line */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/40 to-transparent" aria-hidden="true" />

      {/* Logo */}
      <div
        className={cn(
          'flex items-center h-16 px-4 border-b border-border',
          collapsed ? 'md:justify-center' : 'gap-3'
        )}
      >
        <div className="relative shrink-0">
          <Zap className="h-6 w-6 text-primary" strokeWidth={2.5} />
          <div className="absolute inset-0 blur-sm text-primary opacity-50" aria-hidden="true">
            <Zap className="h-6 w-6" strokeWidth={2.5} />
          </div>
        </div>
        {!collapsed && (
          <div className="flex flex-col min-w-0">
            <span className="font-mono font-bold text-sm text-foreground tracking-wider">
              MIMIC<span className="text-primary">42</span>
            </span>
            <span className="font-mono text-[10px] text-muted-foreground tracking-widest uppercase">
              Управление агентами
            </span>
          </div>
        )}
        {/* Mobile close button */}
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onMobileClose}
          className="ml-auto md:hidden"
          aria-label="Закрыть меню"
        >
          <X className="h-5 w-5" />
        </Button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 overflow-y-auto space-y-1" aria-label="Основная навигация">
        {/* Main nav */}
        {mainNav.map((item) => (
          <SidebarLink
            key={item.href}
            href={item.href}
            label={item.label}
            icon={item.icon}
            isActive={isActive(item.href, item.exact)}
            collapsed={collapsed}
            onNavigate={onMobileClose}
          />
        ))}

        {/* Agents section */}
        {!collapsed && agents && agents.length > 0 && (
          <div className="mt-6 mb-2">
            <p className="px-3 text-xs font-mono text-muted-foreground uppercase tracking-wider mb-1">
              Агенты
            </p>
          </div>
        )}

        {agents?.map((agent) => (
          <Link
            key={agent.agent_id}
            href={`/agent/${agent.agent_id}`}
            onClick={onMobileClose}
            className={cn(
              navItemBase,
              navItemState(isActive(`/agent/${agent.agent_id}`)),
              collapsed ? 'justify-center h-10 w-10 mx-auto' : 'gap-3 px-3 py-2',
            )}
            title={collapsed ? agent.name : undefined}
          >
            <span className="relative shrink-0">
              <Bot className="h-4 w-4" />
              <span
                className={cn(
                  'absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full',
                  agent.state === 'running' && 'bg-success animate-status-pulse',
                  agent.state === 'error' && 'bg-destructive',
                  agent.state === 'starting' && 'bg-primary animate-pulse',
                  (agent.state === 'stopped' || agent.state === 'draft') && 'bg-muted-foreground/50',
                  agent.state === 'stopping' && 'bg-warning animate-pulse',
                )}
                aria-hidden="true"
              />
            </span>
            {!collapsed && (
              <div className="flex-1 min-w-0">
                <p className="font-mono text-sm truncate">{agent.name}</p>
              </div>
            )}
          </Link>
        ))}

        {/* New agent */}
        <Link
          href="/onboarding"
          onClick={onMobileClose}
          className={cn(
            'flex items-center rounded-sm transition-colors duration-150',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
            'text-muted-foreground hover:text-primary hover:bg-primary/5',
            'border border-dashed border-transparent hover:border-primary/40',
            collapsed ? 'justify-center h-10 w-10 mx-auto mt-2' : 'gap-3 px-3 py-2 mt-2',
          )}
          title={collapsed ? 'Новый агент' : undefined}
        >
          <Plus className="h-4 w-4 shrink-0" />
          {!collapsed && <span className="font-mono text-sm">Новый агент</span>}
        </Link>
      </nav>

      {/* Bottom section */}
      <div className="px-3 py-4 border-t border-border space-y-1">
        <Button
          variant="ghost"
          onClick={handleLogout}
          className={cn(
            'w-full h-auto font-normal text-muted-foreground',
            'hover:text-destructive hover:bg-destructive/10',
            collapsed ? 'justify-center p-2' : 'justify-start gap-3 px-3 py-2'
          )}
          title={collapsed ? 'Выйти' : undefined}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {!collapsed && <span className="text-sm">Выйти</span>}
        </Button>
      </div>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className={cn(
          'absolute -right-3 top-20',
          'h-6 w-6 rounded-full',
          'bg-muted border border-border',
          'flex items-center justify-center',
          'text-muted-foreground hover:text-foreground',
          'transition-all duration-150',
          'hover:bg-accent hover:border-accent-foreground/20',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
          'shadow-void',
          'z-10'
        )}
        aria-label={collapsed ? 'Развернуть панель' : 'Свернуть панель'}
      >
        {collapsed ? (
          <ChevronRight className="h-3 w-3" />
        ) : (
          <ChevronLeft className="h-3 w-3" />
        )}
      </button>
    </aside>
    </>
  );
}

// ── Sidebar link component ────────────────────────────────────────────────────
interface SidebarLinkProps {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  isActive: boolean;
  collapsed: boolean;
  badge?: string;
  onNavigate?: () => void;
}

function SidebarLink({ href, label, icon: Icon, isActive, collapsed, badge, onNavigate }: SidebarLinkProps) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      className={cn(
        navItemBase,
        navItemState(isActive),
        collapsed ? 'justify-center h-10 w-10 mx-auto' : 'gap-3 px-3 py-2'
      )}
      title={collapsed ? label : undefined}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {!collapsed && (
        <>
          <span className="font-mono text-sm flex-1">{label}</span>
          {badge && (
            <span className="font-mono text-[10px] bg-primary/10 text-primary border border-primary/30 rounded-sm px-1.5 py-0.5">
              {badge}
            </span>
          )}
        </>
      )}
    </Link>
  );
}
