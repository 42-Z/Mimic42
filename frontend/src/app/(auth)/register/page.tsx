'use client';

import { useState } from 'react';
import Link from 'next/link';
import { getSupabaseClient } from '@/lib/supabase/client';
import { registerSchema, type RegisterFormValues } from '@/lib/validators';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card';
import { useToast } from '@/components/ui/toast';
import { Zap, Eye, EyeOff, CircleCheck } from 'lucide-react';

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
        const key = issue.path[0];
        if (key === 'email' && !fieldErrors.email) fieldErrors.email = issue.message;
        else if (key === 'password' && !fieldErrors.password) fieldErrors.password = issue.message;
        else if (key === 'confirmPassword' && !fieldErrors.confirmPassword) {
          fieldErrors.confirmPassword = issue.message;
        }
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
      <div className="min-h-dvh flex items-center justify-center p-8 pb-[max(2rem,env(safe-area-inset-bottom))]">
        <Card className="w-full max-w-md">
          <div className="flex flex-col items-center gap-4 text-center">
            <CircleCheck className="h-10 w-10 text-success" strokeWidth={1.5} aria-hidden="true" />
            <h1 className="text-2xl font-display font-semibold text-foreground">Проверьте email</h1>
            <p className="text-sm font-mono text-muted-foreground">
              Мы отправили ссылку для подтверждения на{' '}
              <span className="text-foreground">{values.email}</span>
            </p>
            <Link href="/login" className="text-sm font-mono text-primary hover:underline">
              ← Вернуться ко входу
            </Link>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-dvh flex items-center justify-center p-8 pb-[max(2rem,env(safe-area-inset-bottom))]">
      <div className="w-full max-w-md space-y-6">
        <div className="flex items-center justify-center gap-2">
          <Zap className="h-6 w-6 text-plasma-400" />
          <span className="font-mono font-bold text-lg text-foreground">
            MIMIC<span className="text-plasma-400">42</span>
          </span>
        </div>

        <Card padding="none" className="w-full">
          <CardHeader className="pb-4">
            <CardTitle className="text-2xl font-display normal-case tracking-normal text-foreground">
              Создать аккаунт
            </CardTitle>
            <p className="text-sm font-mono text-muted-foreground">Запустите своего первого агента</p>
          </CardHeader>
          <CardContent>
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
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
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
              <Button type="submit" variant="default" className="w-full" size="lg" isLoading={isLoading}>
                {isLoading ? 'Создание...' : 'Создать аккаунт'}
              </Button>
            </form>
          </CardContent>
          <CardFooter className="justify-center">
            <p className="text-xs font-mono text-muted-foreground">
              Уже есть аккаунт?{' '}
              <Link href="/login" className="text-primary hover:underline">
                Войти
              </Link>
            </p>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}
