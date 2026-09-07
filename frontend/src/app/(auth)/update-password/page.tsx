'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { getSupabaseClient } from '@/lib/supabase/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
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
      <div className="min-h-screen bg-void-950 flex items-center justify-center p-8">
        <div className="text-center space-y-4">
          <Zap className="h-8 w-8 text-plasma-400 mx-auto animate-pulse" />
          <p className="font-mono text-sm text-void-400">Проверка сессии...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-void-950 flex items-center justify-center p-8">
      <div className="w-full max-w-sm space-y-8">
        <div className="text-center space-y-2">
          <Zap className="h-8 w-8 text-plasma-400 mx-auto" />
          <h1 className="font-display text-xl font-bold text-neon-400">
            Новый пароль
          </h1>
          <p className="font-mono text-sm text-void-500">
            Введите новый пароль для вашего аккаунта
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            type="password"
            placeholder="Новый пароль"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              if (passwordError) setPasswordError('');
            }}
            error={passwordError}
            required
          />
          <Input
            type="password"
            placeholder="Подтвердите пароль"
            value={confirmPassword}
            onChange={(e) => {
              setConfirmPassword(e.target.value);
              if (passwordError) setPasswordError('');
            }}
            error={passwordError}
            required
          />

          <Button type="submit" className="w-full" size="lg" isLoading={isLoading}>
            {isLoading ? 'Обновление...' : 'Обновить пароль'}
          </Button>
        </form>
      </div>
    </div>
  );
}
