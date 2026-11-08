'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { getSupabaseClient } from '@/lib/supabase/client';
import { updateAccountPassword } from '@/lib/updatePassword';
import { useAccount } from '@/hooks/useAccount';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardHeader, CardTitle, CardContent, Spinner } from '@/components/ui/card';
import { useToast } from '@/components/ui/toast';
import { Zap } from 'lucide-react';

export default function UpdatePasswordPage() {
  const account = useAccount();
  const router = useRouter();
  const { toast } = useToast();
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const isReady = Boolean(account?.userId);
  const redirectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (redirectTimer.current) clearTimeout(redirectTimer.current);
    };
  }, []);

  const validate = () => {
    if (password.length < 8) {
      setPasswordError('Пароль должен быть не менее 8 символов');
      return false;
    }
    // eslint-disable-next-line security/detect-possible-timing-attacks -- compares two user inputs, not a stored secret
    if (password !== confirmPassword) {
      setPasswordError('Пароли не совпадают');
      return false;
    }
    setPasswordError('');
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!account?.userId || account.controller.signal.aborted || isLoading) return;
    if (!validate()) return;

    setIsLoading(true);
    try {
      const supabase = getSupabaseClient();
      await updateAccountPassword(password, {
        userId: account.userId,
        signal: account.controller.signal,
      }, supabase.auth);
      if (account.controller.signal.aborted) return;
      toast('Пароль успешно обновлен', 'success');
      redirectTimer.current = setTimeout(() => {
        if (!account.controller.signal.aborted) router.push('/login');
      }, 1500);
    } catch (error) {
      if (account.controller.signal.aborted) return;
      if (error instanceof Error && error.name === 'AbortError') return;
      toast(error instanceof Error ? error.message : 'Не удалось обновить пароль.', 'error');
    } finally {
      if (!account.controller.signal.aborted) setIsLoading(false);
    }
  };

  if (!isReady) {
    return (
      <div className="min-h-dvh flex items-center justify-center p-8">
        <div className="flex flex-col items-center gap-4 text-center">
          <Spinner size="md" />
          <p className="text-sm font-mono text-muted-foreground">Проверка сессии...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-dvh flex items-center justify-center p-8">
      <div className="w-full max-w-md space-y-6">
        <div className="flex items-center justify-center gap-2">
          <Zap className="h-6 w-6 text-plasma-400" />
          <span className="font-mono font-bold text-lg text-foreground">
            MIMIC<span className="text-plasma-400">42</span>
          </span>
        </div>

        <Card padding="none" className="w-full">
          <CardHeader className="pb-4">
            <CardTitle as="h1" className="text-2xl font-display normal-case tracking-normal text-foreground">
              Новый пароль
            </CardTitle>
            <p className="text-sm font-mono text-muted-foreground">
              Введите новый пароль для вашего аккаунта
            </p>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4" noValidate>
              <Input
                label="Новый пароль"
                type="password"
                placeholder="Минимум 8 символов"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (passwordError) setPasswordError('');
                }}
                error={passwordError}
                required
              />
              <Input
                label="Подтвердите пароль"
                type="password"
                placeholder="••••••••"
                value={confirmPassword}
                onChange={(e) => {
                  setConfirmPassword(e.target.value);
                  if (passwordError) setPasswordError('');
                }}
                error={passwordError}
                required
              />

              <Button type="submit" variant="default" className="w-full" size="lg" isLoading={isLoading}>
                {isLoading ? 'Обновление...' : 'Обновить пароль'}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
