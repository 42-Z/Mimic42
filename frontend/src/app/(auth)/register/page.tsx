'use client';

import { useState } from 'react';
import Link from 'next/link';
import { getSupabaseClient } from '@/lib/supabase/client';
import { registerSchema, type RegisterFormValues } from '@/lib/validators';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useToast } from '@/components/ui/toast';
import { Zap, Eye, EyeOff } from 'lucide-react';

const SUPABASE_ERROR_MESSAGES: Record<string, string> = {
  'User already registered': 'Этот email уже зарегистрирован',
  'Password should be at least 6 characters': 'Пароль должен быть не менее 6 символов',
};

export default function RegisterPage() {
  const { toast } = useToast();

  const [values, setValues] = useState<RegisterFormValues>({
    email: '', password: '', confirmPassword: '',
  });
  const [errors, setErrors] = useState<Partial<RegisterFormValues>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [done, setDone] = useState(false);

  const validate = () => {
    const result = registerSchema.safeParse(values);
    if (!result.success) {
      const fieldErrors: Partial<RegisterFormValues> = {};
      result.error.issues.forEach((issue) => {
        const field = issue.path[0] as keyof RegisterFormValues;
        if (!fieldErrors[field]) fieldErrors[field] = issue.message;
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
      const { error } = await supabase.auth.signUp({
        email: values.email,
        password: values.password,
        options: { emailRedirectTo: `${location.origin}/api/auth/callback` },
      });

      if (error) {
        const message = SUPABASE_ERROR_MESSAGES[error.message] ?? error.message;
        toast(message, 'error');
        return;
      }

      setDone(true);
    } finally {
      setIsLoading(false);
    }
  };

  if (done) {
    return (
      <div className="min-h-screen bg-void-950 flex items-center justify-center p-8">
        <div className="max-w-sm w-full text-center space-y-4">
          <div className="text-4xl">✓</div>
          <h1 className="font-display text-xl font-bold text-neon-400">Проверьте email</h1>
          <p className="font-mono text-sm text-void-400">
            Мы отправили ссылку для подтверждения на{' '}
            <span className="text-void-200">{values.email}</span>
          </p>
          <Link href="/login" className="font-mono text-sm text-plasma-400 hover:text-plasma-300">
            ← Вернуться ко входу
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-void-950 flex items-center justify-center p-8">
      <div className="w-full max-w-sm space-y-8">
        <div className="flex items-center gap-2">
          <Zap className="h-6 w-6 text-plasma-400" />
          <span className="font-mono font-bold text-lg">
            MIMIC<span className="text-plasma-400">42</span>
          </span>
        </div>

        <div>
          <h1 className="font-display text-2xl font-bold text-void-100">Создать аккаунт</h1>
          <p className="mt-1 text-sm font-mono text-void-500">Запустите своего первого агента</p>
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
            autoComplete="new-password"
            placeholder="Минимум 8 символов"
            value={values.password}
            onChange={(e) => setValues((v) => ({ ...v, password: e.target.value }))}
            error={errors.password}
            disabled={isLoading}
            rightElement={
              <button type="button" onClick={() => setShowPassword((v) => !v)}
                className="text-void-500 hover:text-void-300 transition-colors">
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            }
          />
          <Input
            label="Повторите пароль"
            type={showPassword ? 'text' : 'password'}
            autoComplete="new-password"
            placeholder="••••••••"
            value={values.confirmPassword}
            onChange={(e) => setValues((v) => ({ ...v, confirmPassword: e.target.value }))}
            error={errors.confirmPassword}
            disabled={isLoading}
          />
          <Button type="submit" className="w-full mt-2" size="lg" isLoading={isLoading}>
            {isLoading ? 'Создание...' : 'Создать аккаунт'}
          </Button>
        </form>

        <p className="text-center font-mono text-sm text-void-500">
          Уже есть аккаунт?{' '}
          <Link href="/login" className="text-plasma-400 hover:text-plasma-300 transition-colors">
            Войти
          </Link>
        </p>
      </div>
    </div>
  );
}
