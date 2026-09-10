'use client';

import { useEffect, useState } from 'react';
import { getSupabaseClient } from '@/lib/supabase/client';
import { Bell, User } from 'lucide-react';
import type { User as SupabaseUser } from '@supabase/supabase-js';

export function Header() {
  const [user, setUser] = useState<SupabaseUser | null>(null);

  useEffect(() => {
    const supabase = getSupabaseClient();
    supabase.auth.getUser().then(({ data }) => setUser(data.user));
  }, []);

  const email = user?.email ?? '';
  const displayName = email.split('@')[0] ?? 'user';

  return (
    <header className="h-14 border-b border-void-800 bg-void-900/80 backdrop-blur-sm flex items-center justify-between px-6 shrink-0">
      {/* Left: breadcrumb placeholder — pages fill this via portal if needed */}
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-1.5 rounded-full bg-plasma-500 animate-pulse" />
        <span className="font-mono text-xs text-void-500 uppercase tracking-widest">
          Mimic42
        </span>
      </div>

      {/* Right: user info */}
      <div className="flex items-center gap-4">
        <button
          className="text-void-500 hover:text-void-300 transition-colors"
          aria-label="Уведомления"
        >
          <Bell className="h-4 w-4" />
        </button>

        <div className="flex items-center gap-2 px-3 py-1.5 rounded-sm bg-void-800 border border-void-700">
          <div className="h-6 w-6 rounded-sm bg-plasma-950 border border-plasma-800 flex items-center justify-center">
            <User className="h-3 w-3 text-plasma-400" />
          </div>
          <span className="font-mono text-xs text-void-300 hidden sm:block">
            {displayName}
          </span>
        </div>
      </div>
    </header>
  );
}
