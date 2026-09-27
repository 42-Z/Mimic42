'use client';

import { useState } from 'react';
import Link from 'next/link';
import { getSupabaseClient } from '@/lib/supabase/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card';
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
      <div className="min-h-dvh flex items-center justify-center p-8">
        <Card className="w-full max-w-md">
          <div className="flex flex-col items-center gap-4 text-center">
            <Zap className="h-12 w-12 text-plasma-400" aria-hidden="true" />
            <h1 className="text-2xl font-display font-semibold text-foreground">
              Проверьте почту
            </h1>
            <p className="text-sm font-mono text-muted-foreground">
              Мы отправили ссылку для восстановления пароля на{' '}
              <span className="text-foreground">{email}</span>
            </p>
            <Link
              href="/login"
              className="text-sm font-mono text-primary hover:underline"
            >
              ← Вернуться ко входу
            </Link>
          </div>
        </Card>
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
              Восстановление пароля
            </CardTitle>
            <p className="text-sm font-mono text-muted-foreground">
              Введите email, и мы отправим ссылку для сброса
            </p>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4" noValidate>
              <Input
                label="Email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (emailError) setEmailError('');
                }}
                error={emailError}
                required
              />

              <Button type="submit" variant="default" className="w-full" size="lg" isLoading={isLoading}>
                {isLoading ? 'Отправка...' : 'Отправить ссылку'}
              </Button>
            </form>
          </CardContent>
          <CardFooter className="justify-center">
            <p className="text-xs font-mono text-muted-foreground">
              <Link href="/login" className="text-primary hover:underline">
                ← Вернуться ко входу
              </Link>
            </p>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}
