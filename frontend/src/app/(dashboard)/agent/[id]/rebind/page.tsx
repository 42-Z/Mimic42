'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { agentIdSchema } from '@/lib/validators';
import { useTelegramSession } from '@/hooks/useTelegramSession';
import { agentsApi, onboardingApi } from '@/lib/api';
import { queryKeys } from '@/lib/queryClient';
import { needsRebind } from '@/lib/telegram';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, Spinner } from '@/components/ui/card';
import { useToast } from '@/components/ui/toast';
import { maskPhoneNumber } from '@/lib/sanitize';
import {
  telegramCredentialsSchema,
  telegramCodeSchema,
  telegram2FASchema,
} from '@/lib/validators';
import type { ApiError } from '@/types';
import { Bot, CheckCircle2, Link2, MessageSquare, ShieldCheck } from 'lucide-react';
import Link from 'next/link';

type RebindStep = 'phone' | 'code' | '2fa' | 'done';

export default function RebindPage() {
  const params = useParams();
  const rawId = params['id'] as string;
  const parsed = agentIdSchema.safeParse(rawId);
  if (!parsed.success) {
    return <div className="p-8 font-mono text-crimson-400">Недопустимый ID агента</div>;
  }
  return <RebindPageContent agentId={parsed.data} />;
}

function RebindPageContent({ agentId }: { agentId: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: session, isLoading } = useTelegramSession(agentId);

  const [step, setStep] = useState<RebindStep>('phone');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [onboardingId, setOnboardingId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [isPending, setIsPending] = useState(false);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: queryKeys.telegram.byAgent(agentId) });
    qc.invalidateQueries({ queryKey: queryKeys.agents.all });
  };

  const finishRebind = async () => {
    if (!onboardingId) return;
    try {
      await agentsApi.confirmRebind(agentId, { onboarding_id: onboardingId });
      invalidate();
      setStep('done');
    } catch (err: unknown) {
      toast((err as ApiError).message ?? 'Не удалось завершить перепривязку', 'error');
    }
  };

  const handlePhone = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = telegramCredentialsSchema.safeParse({ phone_number: phoneNumber });
    if (!result.success) {
      setError(result.error.issues[0]?.message ?? 'Ошибка');
      return;
    }
    setError('');
    setIsPending(true);
    try {
      const status = await agentsApi.rebindTelegram(agentId, {
        phone_number: result.data.phone_number,
      });
      setOnboardingId(status.onboarding_id);
      setStep('code');
    } catch (err: unknown) {
      toast((err as ApiError).message ?? 'Не удалось отправить код', 'error');
      setError((err as ApiError).message ?? '');
    } finally {
      setIsPending(false);
    }
  };

  const handleCode = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = telegramCodeSchema.safeParse({ code });
    if (!result.success) {
      setError(result.error.issues[0]?.message ?? 'Ошибка');
      return;
    }
    if (!onboardingId) { toast('Сессия перепривязки не найдена', 'error'); return; }
    setError('');
    setIsPending(true);
    try {
      const status = await onboardingApi.submitCode(onboardingId, { code });
      if (status.authorization_status === 'password_required') {
        setStep('2fa');
        return;
      }
      await finishRebind();
    } catch (err: unknown) {
      const apiError = err as ApiError;
      if (apiError.status === 428) {
        setStep('2fa');
      } else {
        setError(apiError.message ?? 'Неверный код');
        toast(apiError.message ?? 'Неверный код', 'error');
      }
    } finally {
      setIsPending(false);
    }
  };

  const handle2FA = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = telegram2FASchema.safeParse({ password });
    if (!result.success) {
      setError(result.error.issues[0]?.message ?? 'Ошибка');
      return;
    }
    if (!onboardingId) { toast('Сессия перепривязки не найдена', 'error'); return; }
    setError('');
    setIsPending(true);
    try {
      await onboardingApi.submitCode(onboardingId, { code, password: result.data.password });
      await finishRebind();
    } catch (err: unknown) {
      setError((err as ApiError).message ?? 'Неверный пароль 2FA');
      toast((err as ApiError).message ?? 'Неверный пароль 2FA', 'error');
    } finally {
      setIsPending(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="max-w-xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center gap-4">
        <div className="h-10 w-10 rounded-sm bg-plasma-950 border border-plasma-800 flex items-center justify-center">
          <Link2 className="h-5 w-5 text-plasma-400" />
        </div>
        <div>
          <h1 className="font-display text-xl font-bold text-void-100">Перепривязка Telegram</h1>
          <p className="font-mono text-xs text-void-500 mt-0.5">
            Сессия недействительна — введите код заново. Имя, память и настройки сохранятся.
          </p>
        </div>
      </div>

      {!needsRebind(session?.authorization_status) && session && (
        <Card variant="glass" padding="md" className="border-neon-900">
          <p className="font-mono text-xs text-neon-400">
            Сессия уже авторизована. Перепривязка не требуется — можно запустить агента.
          </p>
        </Card>
      )}

      {step === 'phone' && (
        <form onSubmit={handlePhone} className="space-y-6">
          <StepBadge step="1" label="Номер телефона" icon={Bot} />
          <Input
            label="Номер телефона"
            type="tel"
            placeholder="+79991234567"
            value={phoneNumber}
            onChange={(e) => setPhoneNumber(e.target.value)}
            error={error}
            hint={session?.phone_number ? `Текущий номер: ${maskPhoneNumber(session.phone_number)}` : 'В формате E.164 с кодом страны'}
            autoFocus
          />
          <Button type="submit" isLoading={isPending} size="lg" className="w-full">
            Получить код →
          </Button>
        </form>
      )}

      {step === 'code' && (
        <form onSubmit={handleCode} className="space-y-6">
          <StepBadge step="2" label="Код из Telegram" icon={MessageSquare} />
          <Input
            label="Код подтверждения"
            type="text"
            inputMode="numeric"
            placeholder="12345"
            maxLength={8}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
            error={error}
            autoFocus
            className="text-center text-xl tracking-[0.5em]"
          />
          <Button type="submit" isLoading={isPending} size="lg" className="w-full">
            Подтвердить →
          </Button>
        </form>
      )}

      {step === '2fa' && (
        <form onSubmit={handle2FA} className="space-y-6">
          <StepBadge step="3" label="Пароль 2FA" icon={ShieldCheck} />
          <div className="p-4 rounded-sm bg-amber-950/20 border border-amber-900/50">
            <p className="font-mono text-xs text-amber-400">
              Это пароль 2FA от Telegram, а не от вашего устройства
            </p>
          </div>
          <Input
            label="Пароль 2FA"
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={error}
            autoFocus
          />
          <Button type="submit" isLoading={isPending} size="lg" className="w-full">
            Подтвердить →
          </Button>
        </form>
      )}

      {step === 'done' && (
        <Card variant="glass" padding="lg" className="space-y-4 text-center">
          <CheckCircle2 className="h-12 w-12 text-neon-400 mx-auto" />
          <h2 className="font-display text-lg font-bold text-void-100">Telegram перепривязан</h2>
          <p className="font-mono text-sm text-void-500">
            Агент пока остановлен — запустите его на странице агента.
          </p>
          <Button onClick={() => router.push(`/agent/${agentId}`)} size="lg" className="w-full">
            К агенту →
          </Button>
        </Card>
      )}

      <div className="text-center">
        <Link
          href={`/agent/${agentId}`}
          className="font-mono text-xs text-void-500 hover:text-void-200 transition-colors"
        >
          ← Вернуться к агенту
        </Link>
      </div>
    </div>
  );
}

function StepBadge({
  step,
  label,
  icon: Icon,
}: {
  step: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="h-8 w-8 rounded-sm bg-plasma-950 border border-plasma-800 flex items-center justify-center">
        <Icon className="h-4 w-4 text-plasma-400" />
      </div>
      <div className="font-mono text-xs text-plasma-500 uppercase tracking-widest">
        Шаг {step} — {label}
      </div>
    </div>
  );
}
