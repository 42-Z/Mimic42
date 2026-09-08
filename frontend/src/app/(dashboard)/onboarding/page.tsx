'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import {
  useOnboardingSession,
  deriveOnboardingStep,
  useSaveAgentName,
  useSaveSoulPrompt,
  useStartTelegramAuth,
  useSubmitTelegramCode,
  useFinalizeAgent,
  useSaveOnboardingStep,
} from '@/hooks/useOnboarding';
import { StepIndicator } from '@/components/onboarding/StepIndicator';
import { Button } from '@/components/ui/button';
import { Input, Textarea } from '@/components/ui/input';
import { Spinner } from '@/components/ui/card';
import { useToast } from '@/components/ui/toast';
import {
  agentNameSchema, soulPromptSchema,
  telegramCredentialsSchema, telegramCodeSchema, telegram2FASchema,
} from '@/lib/validators';
import { cn } from '@/lib/utils';
import { Zap, CheckCircle } from 'lucide-react';
import type { OnboardingStep, OnboardingSessionRow } from '@/types';
import type { ApiError } from '@/types';

import { DEFAULT_SYSTEM_PROMPT } from '@/lib/constants';

export default function OnboardingPage() {
  const { data: session, isLoading } = useOnboardingSession();
  const [telegramCode, setTelegramCodeState] = useState('');

  // Secure client-side synchronization and preventive purging
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const saved = sessionStorage.getItem('_m42_tc_state');
      const status = session?.authorization_status;

      // Immediately purge if authorized, not started, or finished to prevent lingering codes
      if (status === 'authorized' || status === 'not_started' || session?.completed_agent_id) {
        sessionStorage.removeItem('_m42_tc_state');
        setTelegramCodeState('');
      } else if (saved) {
        setTelegramCodeState(saved);
      }
    }
  }, [session]);

  const setTelegramCode = (code: string) => {
    setTelegramCodeState(code);
    if (typeof window !== 'undefined') {
      sessionStorage.setItem('_m42_tc_state', code);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-void-950 flex items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }

  const currentStep = deriveOnboardingStep(session);

  // If already done, redirect
  if (session?.completed_agent_id) {
    return <OnboardingComplete agentId={session.completed_agent_id} />;
  }

  return (
    <div className="min-h-screen bg-void-950">
      <div className="max-w-2xl mx-auto px-6 py-12">
        {/* Logo */}
        <div className="flex items-center gap-2 mb-12">
          <Zap className="h-5 w-5 text-plasma-400" />
          <span className="font-mono font-bold text-sm">
            MIMIC<span className="text-plasma-400">42</span>
          </span>
        </div>

        {/* Progress */}
        <div className="mb-10 overflow-x-auto pb-2">
          <StepIndicator currentStep={currentStep} />
        </div>

        {/* Step content */}
        <div className="animate-slide-in-up">
          <StepRouter
            step={currentStep}
            session={session ?? null}
            telegramCode={telegramCode}
            setTelegramCode={setTelegramCode}
          />
        </div>
      </div>
    </div>
  );
}

function StepRouter({
  step,
  session,
  telegramCode,
  setTelegramCode,
}: {
  step: OnboardingStep;
  session: OnboardingSessionRow | null;
  telegramCode: string;
  setTelegramCode: (val: string) => void;
}) {
  switch (step) {
    case 'name':             return <StepName />;
    case 'soul':             return <StepSoul session={session} />;
    case 'telegram_credentials': return <StepTelegramCredentials session={session} />;
    case 'telegram_code':    return <StepTelegramCode session={session} setTelegramCode={setTelegramCode} />;
    case 'telegram_2fa':     return <StepTelegram2FA session={session} telegramCode={telegramCode} />;
    case 'finalize':         return <StepFinalize session={session} />;
    default:                 return null;
  }
}

// ── Step heading helper ───────────────────────────────────────────────────────
function StepHeading({ step, title, description }: { step: string; title: string; description: string }) {
  return (
    <div className="mb-8">
      <p className="font-mono text-xs text-plasma-500 uppercase tracking-widest mb-2">
        Шаг {step}
      </p>
      <h1 className="font-display text-3xl font-bold text-void-100 mb-2">{title}</h1>
      <p className="font-mono text-sm text-void-500 leading-relaxed">{description}</p>
    </div>
  );
}

// ── Step 1: Name ─────────────────────────────────────────────────────────────
function StepName() {
  const { toast } = useToast();
  const save = useSaveAgentName();
  const [name, setName] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = agentNameSchema.safeParse({ name });
    if (!result.success) {
      setError(result.error.issues[0]?.message ?? 'Ошибка');
      return;
    }
    setError('');
    try {
      await save.mutateAsync({ name });
    } catch {
      toast('Не удалось сохранить. Попробуйте снова.', 'error');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <StepHeading
        step="01 / 04"
        title="Как зовут вашего агента?"
        description="Придумайте имя для агента — оно будет отображаться в панели управления."
      />
      <Input
        label="Имя агента"
        placeholder="Например: Алекс, Помощник, My Bot..."
        value={name}
        onChange={(e) => setName(e.target.value)}
        error={error}
        autoFocus
      />
      <Button type="submit" isLoading={save.isPending} size="lg">
        Продолжить →
      </Button>
    </form>
  );
}

// ── Step 2: Soul ──────────────────────────────────────────────────────────────
function StepSoul({ session }: { session: OnboardingSessionRow | null }) {
  const { toast } = useToast();
  const save = useSaveSoulPrompt();
  const [soulPrompt, setSoulPrompt] = useState('');
  const [error, setError] = useState('');

  const placeholder = `Опиши характер агента: как он общается, какой у него стиль, какие интересы.

Примеры:
- "Дружелюбный, немного саркастичный. Любит IT и музыку 90-х. Отвечает короткими фразами."
- "Серьёзный, профессиональный. Говорит официально, избегает сленга. Внимательный к деталям."`;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = soulPromptSchema.safeParse({ soul_prompt: soulPrompt });
    if (!result.success) {
      setError(result.error.issues[0]?.message ?? 'Ошибка');
      return;
    }
    setError('');
    try {
      await save.mutateAsync({ soul_prompt: soulPrompt });
    } catch {
      toast('Не удалось сохранить', 'error');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <StepHeading
        step="02 / 04"
        title="Характер агента"
        description="Опишите личность, стиль общения и особенности вашего агента. Чем подробнее — тем естественнее поведение."
      />
      <div className="p-4 rounded-sm bg-plasma-950/30 border border-plasma-900/50 font-mono text-xs text-plasma-400">
        💡 SOUL.md — это душа вашего агента. Здесь задаётся всё: от манеры речи до любимых тем.
      </div>
      <Textarea
        label={`SOUL.md — ${session?.agent_name ?? 'Агент'}`}
        placeholder={placeholder}
        value={soulPrompt}
        onChange={(e) => setSoulPrompt(e.target.value)}
        error={error}
        className="min-h-[220px]"
        showCount
        maxLength={50000}
        autoFocus
      />
      <div className="flex gap-3">
        <Button type="submit" isLoading={save.isPending} size="lg">
          Продолжить →
        </Button>
      </div>
    </form>
  );
}

// ── Step 4a: Telegram credentials ────────────────────────────────────────────
function StepTelegramCredentials({ session }: { session: OnboardingSessionRow | null }) {
  const { toast } = useToast();
  const startAuth = useStartTelegramAuth();
  const [values, setValues] = useState({ phone_number: '' });
  const [errors, setErrors] = useState<Partial<typeof values>>({});

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = telegramCredentialsSchema.safeParse(values);
    if (!result.success) {
      const fe: Partial<typeof values> = {};
      result.error.issues.forEach((issue) => {
        const f = issue.path[0] as keyof typeof values;
        if (!fe[f]) fe[f] = issue.message;
      });
      setErrors(fe);
      return;
    }
    setErrors({});
    try {
      await startAuth.mutateAsync(result.data);
    } catch (e: unknown) {
      toast((e as ApiError).message ?? 'Ошибка авторизации', 'error');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <StepHeading
        step="03 / 04"
        title="Подключение Telegram"
        description="Авторизуйтесь как пользователь, а не как бот. Введите номер — на него придёт код подтверждения."
      />

      <div className="space-y-4">
        <Input
          label="Номер телефона"
          type="tel"
          placeholder="+79991234567"
          value={values.phone_number}
          onChange={(e) => setValues((v) => ({ ...v, phone_number: e.target.value }))}
          error={errors.phone_number}
          hint="В формате E.164 с кодом страны"
        />
      </div>

      <Button type="submit" isLoading={startAuth.isPending} size="lg">
        {startAuth.isPending ? 'Отправка кода...' : 'Получить код →'}
      </Button>
    </form>
  );
}

// ── Step 4b: Code ─────────────────────────────────────────────────────────────
function StepTelegramCode({
  session,
  setTelegramCode,
}: {
  session: OnboardingSessionRow | null;
  setTelegramCode: (val: string) => void;
}) {
  const { toast } = useToast();
  const submitCode = useSubmitTelegramCode();
  const save = useSaveOnboardingStep();
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [isBacking, setIsBacking] = useState(false);

  const handleBack = async () => {
    setIsBacking(true);
    try {
      if (typeof window !== 'undefined') {
        sessionStorage.removeItem('_m42_tc_state');
      }
      await save.mutateAsync({ authorization_status: 'not_started' });
    } catch {
      toast('Не удалось вернуться назад', 'error');
    } finally {
      setIsBacking(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = telegramCodeSchema.safeParse({ code });
    if (!result.success) {
      setError(result.error.issues[0]?.message ?? 'Ошибка');
      return;
    }
    setError('');
    if (!session?.id) { toast('Сессия не найдена', 'error'); return; }
    try {
      setTelegramCode(code);
      await submitCode.mutateAsync({ onboardingId: session.id, code });
    } catch (e: unknown) {
      const err = e as ApiError;
      if (err.status === 428) {
        // 2FA required — handled by step change
      } else {
        toast(err.message ?? 'Неверный код', 'error');
        setError(err.message ?? 'Неверный код');
      }
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <StepHeading
        step="03 / 04"
        title="Код из Telegram"
        description={`Telegram отправил код на номер ${session?.phone_number ?? ''}. Введите его ниже.`}
      />
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
      <div className="flex gap-4">
        <Button
          type="button"
          variant="outline"
          onClick={handleBack}
          isLoading={isBacking}
          disabled={submitCode.isPending}
          size="lg"
        >
          ← Назад
        </Button>
        <Button
          type="submit"
          isLoading={submitCode.isPending}
          disabled={isBacking}
          size="lg"
          className="flex-1"
        >
          Подтвердить →
        </Button>
      </div>
    </form>
  );
}

// ── Step 4c: 2FA ──────────────────────────────────────────────────────────────
function StepTelegram2FA({
  session,
  telegramCode,
}: {
  session: OnboardingSessionRow | null;
  telegramCode: string;
}) {
  const { toast } = useToast();
  const submitCode = useSubmitTelegramCode();
  const save = useSaveOnboardingStep();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isBacking, setIsBacking] = useState(false);

  const handleBack = async () => {
    setIsBacking(true);
    try {
      if (typeof window !== 'undefined') {
        sessionStorage.removeItem('_m42_tc_state');
      }
      await save.mutateAsync({ authorization_status: 'not_started' });
    } catch {
      toast('Не удалось вернуться назад', 'error');
    } finally {
      setIsBacking(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = telegram2FASchema.safeParse({ password });
    if (!result.success) {
      setError(result.error.issues[0]?.message ?? 'Ошибка');
      return;
    }
    setError('');
    if (!session?.id) { toast('Сессия не найдена', 'error'); return; }
    try {
      await submitCode.mutateAsync({ onboardingId: session.id, code: telegramCode, password });
    } catch (e: unknown) {
      toast((e as ApiError).message ?? 'Неверный пароль 2FA', 'error');
      setError('Неверный пароль');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <StepHeading
        step="03 / 04"
        title="Двухфакторная аутентификация"
        description="На вашем аккаунте включена 2FA. Введите пароль облачного хранилища Telegram."
      />
      <div className="p-4 rounded-sm bg-amber-950/20 border border-amber-900/50">
        <p className="font-mono text-xs text-amber-400">
          ⚠ Это пароль 2FA от Telegram, не от вашего устройства
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
      <div className="flex gap-4">
        <Button
          type="button"
          variant="outline"
          onClick={handleBack}
          isLoading={isBacking}
          disabled={submitCode.isPending}
          size="lg"
        >
          ← Назад
        </Button>
        <Button
          type="submit"
          isLoading={submitCode.isPending}
          disabled={isBacking}
          size="lg"
          className="flex-1"
        >
          Подтвердить →
        </Button>
      </div>
    </form>
  );
}

// ── Step 5: Finalize ──────────────────────────────────────────────────────────
function StepFinalize({ session }: { session: OnboardingSessionRow | null }) {
  const { toast } = useToast();
  const finalize = useFinalizeAgent();

  const handleFinalize = async () => {
    if (!session?.id) { toast('Сессия не найдена', 'error'); return; }
    try {
      await finalize.mutateAsync({ onboardingId: session.id, session });
    } catch (e: unknown) {
      toast((e as ApiError).message ?? 'Ошибка создания агента', 'error');
    }
  };

  return (
    <div className="space-y-6">
      <StepHeading
        step="04 / 04"
        title="Всё готово!"
        description="Проверьте данные агента и запустите его."
      />

      <div className="space-y-3">
        {[
          { label: 'Имя', value: session?.agent_name ?? '—' },
          { label: 'Telegram', value: session?.phone_number ?? '—' },
          { label: 'Авторизация', value: session?.authorization_status === 'authorized' ? '✓ Авторизован' : '—' },
        ].map((row) => (
          <div key={row.label} className="flex items-center justify-between py-3 border-b border-void-800">
            <span className="font-mono text-xs text-void-500 uppercase tracking-wider">{row.label}</span>
            <span className="font-mono text-sm text-void-200">{row.value}</span>
          </div>
        ))}
      </div>

      <Button
        onClick={handleFinalize}
        isLoading={finalize.isPending}
        size="lg"
        className="w-full"
      >
        {finalize.isPending ? 'Создание агента...' : '🚀 Создать агента'}
      </Button>
    </div>
  );
}

// ── Complete ──────────────────────────────────────────────────────────────────
function OnboardingComplete({ agentId }: { agentId: string }) {
  const router = useRouter();
  return (
    <div className="min-h-screen bg-void-950 flex items-center justify-center p-8">
      <div className="text-center space-y-6 max-w-sm">
        <CheckCircle className="h-16 w-16 text-neon-400 mx-auto" />
        <h1 className="font-display text-2xl font-bold text-void-100">Агент создан!</h1>
        <p className="font-mono text-sm text-void-500">
          Ваш агент готов к работе. Перейдите в дашборд чтобы запустить его.
        </p>
        <Button onClick={() => router.push('/dashboard')} size="lg" className="w-full">
          Открыть Dashboard →
        </Button>
      </div>
    </div>
  );
}
