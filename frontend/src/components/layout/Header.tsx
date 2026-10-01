'use client';

import { useEffect, useState } from 'react';
import { getSupabaseClient } from '@/lib/supabase/client';
import { Menu, User } from 'lucide-react';
import type { User as SupabaseUser } from '@supabase/supabase-js';
import { Button } from '@/components/ui/button';

interface HeaderProps {
  onMenuClick?: () => void;
}

export function Header({ onMenuClick }: HeaderProps) {
  const [user, setUser] = useState<SupabaseUser | null>(null);

  useEffect(() => {
    const supabase = getSupabaseClient();
    supabase.auth.getUser().then(({ data }) => setUser(data.user));
  }, []);

  const email = user?.email ?? '';
  const displayName = email.split('@')[0] ?? 'user';

  return (
    <header className="h-14 border-b border-border bg-card/60 backdrop-blur-sm flex items-center justify-between px-4 sm:px-6 shrink-0">
      {/* Left: mobile menu + brand */}
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onMenuClick}
          className="md:hidden -ml-1"
          aria-label="Открыть меню"
        >
          <Menu className="h-5 w-5" />
        </Button>
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" aria-hidden="true" />
          <span className="font-mono text-xs text-muted-foreground uppercase tracking-widest">
            Mimic42
          </span>
        </div>
      </div>

      {/* Right: user info */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-sm bg-card border border-border">
          <div className="h-6 w-6 rounded-sm bg-primary/10 border border-primary/20 flex items-center justify-center" aria-hidden="true">
            <User className="h-3 w-3 text-primary" />
          </div>
          <span className="font-mono text-xs text-foreground hidden sm:block">
            {displayName}
          </span>
        </div>
      </div>
    </header>
  );
}
