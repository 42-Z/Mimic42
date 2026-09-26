'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { getSupabaseClient } from '@/lib/supabase/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardHeader, CardTitle, CardContent, Spinner } from '@/components/ui/card';
import { useToast } from '@/components/ui/toast';
import { Zap } from 'lucide-react';

export default function UpdatePasswordPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    const supabase = getSupabaseClient();
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'PASSWORD_RECOVERY') {
        setIsReady(true);
      }
    });

    // Also check if we already have a session (user clicked link and was redirected)
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        setIsReady(true);
      }
    });

    return () => subscription.unsubscribe();
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
    if (!validate()) return;

    setIsLoading(true);
    try {
      const supabase = getSupabaseClient();
      const { error } = await supabase.auth.updateUser({ password });

      if (error) {
        toast(error.message, 'error');
      } else {
        toast('Пароль успешно обновлен', 'success');
        setTimeout(() => router.push('/login'), 1500);
      }
    } finally {
      setIsLoading(false);
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
            <CardTitle className="text-2xl font-display normal-case tracking-normal text-foreground">
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
