'use client';

import { useState } from 'react';
import Link from 'next/link';
import { getSupabaseClient } from '@/lib/supabase/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useToast } from '@/components/ui/toast';
import { Zap } from 'lucide-react';
import { emailSchema } from '@/lib/validators';

export default function ResetPasswordPage() {
  const { toast } = useToast();
  const [email, setEmail] = useState('');
  const [emailError, setEmailError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const validate = () => {
    const result = emailSchema.safeParse(email);
    if (!result.success) {
      setEmailError('Введите корректный email');
      return false;
    }
    setEmailError('');
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    setIsLoading(true);
    try {
      const supabase = getSupabaseClient();
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/update-password`,
      });

      if (error) {
        toast(error.message, 'error');
      } else {
        setSent(true);
        toast('Письмо для восстановления пароля отправлено', 'success');
      }
    } finally {
      setIsLoading(false);
    }
  };

  if (sent) {
    return (
      <div className="min-h-screen bg-void-950 flex items-center justify-center p-8">
        <div className="w-full max-w-sm space-y-8 text-center">
          <Zap className="h-12 w-12 text-plasma-400 mx-auto" />
          <h1 className="font-display text-xl font-bold text-neon-400">
            Проверьте почту
          </h1>
          <p className="font-mono text-sm text-void-400">
            Мы отправили ссылку для восстановления пароля на{' '}
            <span className="text-void-200">{email}</span>
          </p>
          <Link
            href="/login"
            className="inline-block font-mono text-sm text-plasma-400 hover:text-plasma-300 transition-colors"
          >
            ← Вернуться ко входу
          </Link>
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
            Восстановление пароля
          </h1>
          <p className="font-mono text-sm text-void-500">
            Введите email, и мы отправим ссылку для сброса
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <Input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              if (emailError) setEmailError('');
            }}
            error={emailError}
            required
          />

          <Button type="submit" className="w-full" size="lg" isLoading={isLoading}>
            {isLoading ? 'Отправка...' : 'Отправить ссылку'}
          </Button>
        </form>

        <p className="text-center font-mono text-sm text-void-500">
          <Link href="/login" className="text-plasma-400 hover:text-plasma-300 transition-colors">
            ← Вернуться ко входу
          </Link>
        </p>
      </div>
    </div>
  );
}
