'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { agentIdSchema } from '@/lib/validators';
import { useTelegramSession } from '@/hooks/useTelegramSession';
import { agentsApi, onboardingApi } from '@/lib/api';
import { queryKeys } from '@/lib/queryClient';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, Spinner } from '@/components/ui/card';
import { useToast } from '@/components/ui/toast';
import { maskPhoneNumber } from '@/lib/sanitize';
import { telegramCodeSchema, telegram2FASchema } from '@/lib/validators';
import type { ApiError } from '@/types';
import { CheckCircle2, Link2, MessageSquare, ShieldCheck } from 'lucide-react';
import Link from 'next/link';

type RebindStep = 'starting' | 'code' | '2fa' | 'confirm-failed' | 'done';

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
  const { data: session } = useTelegramSession(agentId);

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: queryKeys.telegram.byAgent(agentId) });
    void qc.invalidateQueries({ queryKey: queryKeys.agents.all });
  };

  return (
    <RebindWizard
      agentId={agentId}
      knownPhone={session?.phone_number ?? null}
      onNavigate={(href) => router.push(href)}
      onInvalidate={invalidate}
      onToast={toast}
    />
  );
}

interface RebindWizardProps {
  agentId: string;
  knownPhone: string | null;
  onNavigate: (href: string) => void;
  onInvalidate: () => void;
  onToast: (message: string, variant: 'success' | 'error') => void;
}

export function RebindWizard({
  agentId,
  knownPhone,
  onNavigate,
  onInvalidate,
  onToast,
}: RebindWizardProps) {
  const [step, setStep] = useState<RebindStep>('starting');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [onboardingId, setOnboardingId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [isPending, setIsPending] = useState(false);
  const [isResending, setIsResending] = useState(false);

  const requestedRef = useRef(false);

  const requestCode = useCallback(async () => {
    setError('');
    setIsPending(true);
    try {
      const status = await agentsApi.rebindTelegram(agentId);
      setOnboardingId(status.onboarding_id);
      setStep('code');
    } catch (err: unknown) {
      const message = (err as ApiError).message ?? 'Не удалось отправить код';
      setError(message);
      onToast(message, 'error');
    } finally {
      setIsPending(false);
    }
  }, [agentId, onToast]);

  useEffect(() => {
    if (requestedRef.current) return;
    requestedRef.current = true;
    void requestCode();
  }, [requestCode]);

  const finishRebind = async () => {
    if (!onboardingId) return;
    setIsPending(true);
    setError('');
    try {
      await agentsApi.confirmRebind(agentId, { onboarding_id: onboardingId });
      onInvalidate();
      setStep('done');
    } catch (err: unknown) {
      const apiError = err as ApiError;
      const message = apiError.message ?? 'Не удалось завершить перепривязку';
      if (apiError.status === 404) {
        onToast(message, 'error');
        await requestCode();
        return;
      }
      if (apiError.status !== undefined && apiError.status < 500) {
        setError(message);
        onToast(message, 'error');
        setStep('code');
        return;
      }
      // Код уже израсходован, повторный submitCode его не примет: даём
      // повторить именно подтверждение только при сетевом/5xx-сбое.
      setError(message);
      onToast(message, 'error');
      setStep('confirm-failed');
    } finally {
      setIsPending(false);
    }
  };

  const resendCode = async () => {
    setError('');
    setIsResending(true);
    try {
      const status = await agentsApi.rebindTelegram(agentId);
      setOnboardingId(status.onboarding_id);
      setCode('');
      onToast('Код отправлен повторно', 'success');
    } catch (err: unknown) {
      const message = (err as ApiError).message ?? 'Не удалось отправить код';
      setError(message);
      onToast(message, 'error');
    } finally {
      setIsResending(false);
    }
  };

  const handleCode = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = telegramCodeSchema.safeParse({ code });
    if (!result.success) {
      setError(result.error.issues[0]?.message ?? 'Ошибка');
      return;
    }
    if (!onboardingId) {
      onToast('Сессия перепривязки не найдена', 'error');
      return;
    }
    setError('');
    setIsPending(true);
    try {
      const status = await onboardingApi.submitCode(onboardingId, { code });
      if (status.authorization_status === 'password_required') {
        setStep('2fa');
        return;
      }
      if (status.authorization_status !== 'authorized') {
        setError('Не удалось подтвердить код. Попробуйте ещё раз.');
        onToast('Не удалось подтвердить код', 'error');
        return;
      }
      await finishRebind();
    } catch (err: unknown) {
      const apiError = err as ApiError;
      if (apiError.status === 428) {
        setStep('2fa');
      } else {
        setError(apiError.message ?? 'Неверный код');
        onToast(apiError.message ?? 'Неверный код', 'error');
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
    if (!onboardingId) {
      onToast('Сессия перепривязки не найдена', 'error');
      return;
    }
    setError('');
    setIsPending(true);
    try {
      await onboardingApi.submitCode(onboardingId, { code, password: result.data.password });
      await finishRebind();
    } catch (err: unknown) {
      setError((err as ApiError).message ?? 'Неверный пароль 2FA');
      onToast((err as ApiError).message ?? 'Неверный пароль 2FA', 'error');
    } finally {
      setIsPending(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center gap-4">
        <div className="h-10 w-10 rounded-sm bg-plasma-950 border border-plasma-800 flex items-center justify-center">
          <Link2 className="h-5 w-5 text-plasma-400" />
        </div>
        <div>
          <h1 className="font-display text-xl font-bold text-void-100">Перепривязка Telegram</h1>
          <p className="font-mono text-xs text-void-500 mt-0.5">
            Введите код из Telegram. Имя, память и настройки сохранятся.
          </p>
        </div>
      </div>

      {step === 'starting' && (
        <Card variant="glass" padding="lg" className="flex flex-col items-center gap-4 text-center">
          {isPending ? (
            <>
              <Spinner size="lg" />
              <p className="font-mono text-sm text-void-400">Отправляем код в Telegram…</p>
            </>
          ) : (
            <>
              <p className="font-mono text-sm text-crimson-400">
                {error || 'Не удалось отправить код'}
              </p>
              <Button onClick={() => void requestCode()} size="lg" className="w-full">
                Повторить
              </Button>
            </>
          )}
        </Card>
      )}

      {step === 'code' && (
        <form onSubmit={handleCode} className="space-y-6">
          <StepBadge step="1" label="Код из Telegram" icon={MessageSquare} />
          <Input
            label="Код подтверждения"
            type="text"
            inputMode="numeric"
            placeholder="12345"
            maxLength={8}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
            error={error}
            hint={knownPhone ? `Код придёт в Telegram на ${maskPhoneNumber(knownPhone)}` : undefined}
            autoFocus
            className="text-center text-xl tracking-[0.5em]"
          />
          <Button
            type="submit"
            isLoading={isPending}
            disabled={isResending}
            size="lg"
            className="w-full"
          >
            Подтвердить →
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={resendCode}
            isLoading={isResending}
            disabled={isPending}
            className="w-full"
          >
            Отправить код ещё раз
          </Button>
        </form>
      )}

      {step === '2fa' && (
        <form onSubmit={handle2FA} className="space-y-6">
          <StepBadge step="2" label="Пароль 2FA" icon={ShieldCheck} />
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

      {step === 'confirm-failed' && (
        <Card variant="glass" padding="lg" className="flex flex-col items-center gap-4 text-center">
          <p className="font-mono text-sm text-crimson-400">
            {error || 'Не удалось завершить перепривязку'}
          </p>
          <p className="font-mono text-xs text-void-500">
            Telegram уже привязан — осталось пересобрать агента.
          </p>
          <Button
            onClick={() => void finishRebind()}
            isLoading={isPending}
            size="lg"
            className="w-full"
          >
            Повторить
          </Button>
        </Card>
      )}

      {step === 'done' && (
        <Card variant="glass" padding="lg" className="space-y-4 text-center">
          <CheckCircle2 className="h-12 w-12 text-neon-400 mx-auto" />
          <h2 className="font-display text-lg font-bold text-void-100">Telegram перепривязан</h2>
          <p className="font-mono text-sm text-void-500">
            Агент пока остановлен — запустите его на странице агента.
          </p>
          <Button onClick={() => onNavigate(`/agent/${agentId}`)} size="lg" className="w-full">
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
