'use client';

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { getSupabaseClient } from '@/lib/supabase/client';
import { loginSchema, type LoginFormValues } from '@/lib/validators';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useToast } from '@/components/ui/toast';
import { Zap, Eye, EyeOff } from 'lucide-react';
import { cn } from '@/lib/utils';

const SUPABASE_ERROR_MESSAGES: Record<string, string> = {
  'Invalid login credentials': 'Неверный email или пароль',
  'Email not confirmed': 'Подтвердите email перед входом',
  'Too many requests': 'Слишком много попыток. Подождите немного',
};

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { toast } = useToast();

  const [values, setValues] = useState<LoginFormValues>({ email: '', password: '' });
  const [errors, setErrors] = useState<Partial<LoginFormValues>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [terminalLines, setTerminalLines] = useState<string[]>([]);

  // Terminal typing effect on mount
  useEffect(() => {
    const lines = [
      '> Initializing MIMIC42 control panel...',
      '> Loading agent protocols...',
      '> Connecting to Supabase cluster...',
      '> Ready. Awaiting authentication.',
    ];
    const queue = [...lines];
    const interval = setInterval(() => {
      const line = queue.shift();
      if (line === undefined) {
        clearInterval(interval);
        return;
      }
      setTerminalLines((prev) => [...prev, line]);
    }, 400);
    return () => clearInterval(interval);
  }, []);

  // Show redirect error if any
  useEffect(() => {
    if (searchParams.get('error') === 'auth_callback_failed') {
      toast('Ошибка аутентификации. Попробуйте снова.', 'error');
    }
  }, [searchParams, toast]);

  const validate = () => {
    const result = loginSchema.safeParse(values);
    if (!result.success) {
      const fieldErrors: Partial<LoginFormValues> = {};
      result.error.issues.forEach((issue) => {
        const key = issue.path[0];
        if (key === 'email') fieldErrors.email = issue.message;
        else if (key === 'password') fieldErrors.password = issue.message;
      });
      setErrors(fieldErrors);
      return false;
    }
    setErrors({});
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    setIsLoading(true);
    try {
      const supabase = getSupabaseClient();
      const { error } = await supabase.auth.signInWithPassword({
        email: values.email,
        password: values.password,
      });

      if (error) {
        const message = SUPABASE_ERROR_MESSAGES[error.message] ?? error.message;
        toast(message, 'error');
        return;
      }

      const redirect = searchParams.get('redirect') ?? '/dashboard';
      router.push(redirect);
      router.refresh();
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-dvh bg-void-950 flex">
      {/* Left: terminal panel */}
      <div className="hidden lg:flex w-1/2 flex-col justify-between p-12 bg-void-900 border-r border-void-800 relative overflow-hidden">
        <div className="absolute inset-0 bg-plasma-glow opacity-30" />
        <div className="absolute inset-0 scanline" />

        {/* Logo */}
        <div className="relative flex items-center gap-3">
          <div className="relative">
            <Zap className="h-8 w-8 text-plasma-400" strokeWidth={2.5} />
            <div className="absolute inset-0 blur-md text-plasma-400 opacity-60">
              <Zap className="h-8 w-8" />
            </div>
          </div>
          <div>
            <div className="font-mono font-bold text-xl text-void-100 tracking-wider">
              MIMIC<span className="text-plasma-400">42</span>
            </div>
            <div className="font-mono text-[11px] text-void-500 tracking-widest uppercase">
              Agent Control Panel
            </div>
          </div>
        </div>

        {/* Terminal output */}
        <div className="relative font-mono text-sm space-y-1">
          {terminalLines.map((line, i) => (
            <p
              key={i}
              className={cn(
                'text-neon-400 animate-fade-in',
                i === terminalLines.length - 1 && 'text-void-200'
              )}
            >
              {line}
              {i === terminalLines.length - 1 && (
                <span className="inline-block w-2 h-4 bg-void-200 ml-1 animate-blink align-text-bottom" />
              )}
            </p>
          ))}
        </div>

        {/* Bottom tag */}
        <p className="relative font-mono text-xs text-void-600">
          v0.1.0 — Реалистичный ИИ-агент для Telegram
        </p>
      </div>

      {/* Right: login form */}
      <div className="flex-1 flex flex-col items-center justify-center p-8">
        <div className="w-full max-w-sm space-y-8">
          {/* Mobile logo */}
          <div className="lg:hidden flex items-center gap-2 mb-8">
            <Zap className="h-6 w-6 text-plasma-400" />
            <span className="font-mono font-bold text-lg">
              MIMIC<span className="text-plasma-400">42</span>
            </span>
          </div>

          <div>
            <h1 className="font-display text-2xl font-bold text-void-100">
              Вход в систему
            </h1>
            <p className="mt-1 text-sm font-mono text-void-500">
              Управляйте своим агентом
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <Input
              label="Email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={values.email}
              onChange={(e) => setValues((v) => ({ ...v, email: e.target.value }))}
              error={errors.email}
              disabled={isLoading}
            />

            <Input
              label="Пароль"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              placeholder="••••••••"
              value={values.password}
              onChange={(e) => setValues((v) => ({ ...v, password: e.target.value }))}
              error={errors.password}
              disabled={isLoading}
              rightElement={
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="text-void-500 hover:text-void-300 transition-colors p-2 -m-1"
                  aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              }
            />

            <div className="flex justify-end">
              <Link
                href="/reset-password"
                className="font-mono text-xs text-void-500 hover:text-plasma-300 transition-colors py-2"
              >
                Забыли пароль?
              </Link>
            </div>

            <Button
              type="submit"
              className="w-full"
              size="lg"
              isLoading={isLoading}
            >
              {isLoading ? 'Вход...' : 'Войти'}
            </Button>
          </form>

          <p className="text-center font-mono text-sm text-void-500">
            Нет аккаунта?{' '}
            <Link href="/register" className="text-plasma-400 hover:text-plasma-300 transition-colors inline-block py-2">
              Зарегистрироваться
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-dvh bg-void-950 flex items-center justify-center font-mono text-void-500">Loading...</div>}>
      <LoginContent />
    </Suspense>
  );
}
