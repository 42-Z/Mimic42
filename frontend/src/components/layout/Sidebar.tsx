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
  Zap,
  X,
} from 'lucide-react';
import { getSupabaseClient } from '@/lib/supabase/client';
import { useRouter } from 'next/navigation';
import { useAgents } from '@/hooks/useAgents';
import type { AgentState } from '@/types';

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  exact?: boolean;
}

const mainNav: NavItem[] = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, exact: true },
];

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
          'relative flex flex-col h-screen',
          'bg-void-900 border-r border-void-700',
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
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-plasma-600/40 to-transparent" />

      {/* Logo */}
      <div
        className={cn(
          'flex items-center h-16 px-4 border-b border-void-800',
          collapsed ? 'md:justify-center' : 'gap-3'
        )}
      >
        <div className="relative shrink-0">
          <Zap className="h-6 w-6 text-plasma-400" strokeWidth={2.5} />
          <div className="absolute inset-0 blur-sm text-plasma-400 opacity-50">
            <Zap className="h-6 w-6" strokeWidth={2.5} />
          </div>
        </div>
        {!collapsed && (
          <div className="flex flex-col min-w-0">
            <span className="font-mono font-bold text-sm text-void-100 tracking-wider">
              MIMIC<span className="text-plasma-400">42</span>
            </span>
            <span className="font-mono text-[10px] text-void-500 tracking-widest uppercase">
              Agent Control
            </span>
          </div>
        )}
        {/* Mobile close button */}
        <button
          onClick={onMobileClose}
          className="ml-auto md:hidden text-void-500 hover:text-void-300 transition-colors"
          aria-label="Закрыть меню"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 overflow-y-auto space-y-1">
        {/* Main nav */}
        {mainNav.map((item) => (
          <SidebarLink
            key={item.href}
            href={item.href}
            label={item.label}
            icon={item.icon}
            isActive={isActive(item.href, item.exact)}
            collapsed={collapsed}
          />
        ))}

        {/* Agents section */}
        {!collapsed && agents && agents.length > 0 && (
          <div className="mt-6 mb-2">
            <p className="px-3 text-[10px] font-mono text-void-600 uppercase tracking-widest mb-1">
              Агенты
            </p>
          </div>
        )}

        {agents?.map((agent) => (
          <Link
            key={agent.agent_id}
            href={`/agent/${agent.agent_id}`}
            className={cn(
              'flex items-center rounded-sm transition-colors duration-150',
              'hover:bg-void-800 text-void-400 hover:text-void-100',
              isActive(`/agent/${agent.agent_id}`) &&
                'bg-void-800 text-void-100',
              collapsed ? 'justify-center h-10 w-10 mx-auto' : 'gap-3 px-3 py-2',
            )}
            title={collapsed ? agent.name : undefined}
          >
            <div className="relative shrink-0">
              <Bot className="h-4 w-4" />
              <span
                className={cn(
                  'absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full',
                  agent.state === 'running' && 'bg-neon-400 animate-status-pulse',
                  agent.state === 'error' && 'bg-crimson-400',
                  agent.state === 'starting' && 'bg-plasma-400 animate-pulse',
                  (agent.state === 'stopped' || agent.state === 'draft') && 'bg-void-600',
                  agent.state === 'stopping' && 'bg-amber-400 animate-pulse',
                )}
              />
            </div>
            {!collapsed && (
              <div className="flex-1 min-w-0">
                <p className="font-mono text-sm truncate">{agent.name}</p>
              </div>
            )}
          </Link>
        ))}
      </nav>

      {/* Bottom section */}
      <div className="px-3 py-4 border-t border-void-800 space-y-1">
        <button
          onClick={handleLogout}
          className={cn(
            'flex items-center w-full rounded-sm',
            'text-void-500 hover:text-crimson-400 hover:bg-crimson-950/30',
            'transition-colors duration-150',
            collapsed ? 'justify-center h-10' : 'gap-3 px-3 py-2'
          )}
          title={collapsed ? 'Выйти' : undefined}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {!collapsed && <span className="font-mono text-sm">Выйти</span>}
        </button>
      </div>

      {/* Collapse toggle (desktop only) */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className={cn(
          'absolute -right-3 top-20',
          'h-6 w-6 rounded-full',
          'bg-void-700 border border-void-600',
          'items-center justify-center',
          'text-void-400 hover:text-void-100',
          'transition-all duration-150',
          'hover:bg-void-600 hover:border-void-500',
          'shadow-void',
          'z-10',
          'hidden md:flex'
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
}

function SidebarLink({ href, label, icon: Icon, isActive, collapsed, badge }: SidebarLinkProps) {
  return (
    <Link
      href={href}
      className={cn(
        'flex items-center rounded-sm transition-all duration-150',
        isActive
          ? 'bg-plasma-950/60 text-plasma-400 border border-plasma-900'
          : 'text-void-400 hover:text-void-100 hover:bg-void-800 border border-transparent',
        collapsed ? 'justify-center h-10 w-10 mx-auto' : 'gap-3 px-3 py-2'
      )}
      title={collapsed ? label : undefined}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {!collapsed && (
        <>
          <span className="font-mono text-sm flex-1">{label}</span>
          {badge && (
            <span className="font-mono text-[10px] bg-plasma-950 text-plasma-400 border border-plasma-800 rounded-[2px] px-1.5 py-0.5">
              {badge}
            </span>
          )}
        </>
      )}
    </Link>
  );
}
