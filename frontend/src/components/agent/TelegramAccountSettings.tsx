'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { formatDistanceToNow } from 'date-fns';
import { ru } from 'date-fns/locale';
import { useQueryClient } from '@tanstack/react-query';

import { useTelegramPasswordState } from '@/hooks/useAgent';
import { agentsApi } from '@/lib/api';
import { queryKeys } from '@/lib/queryClient';
import { Badge } from '@/components/ui/card';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field';
import { Separator } from '@/components/ui/separator';
import { maskPhoneNumber } from '@/lib/sanitize';
import { formatTelegramUsername } from '@/components/agents/AgentIdentity';
import type { ApiError, TelegramSessionRow } from '@/types';

const USERNAME_PATTERN = /^[A-Za-z0-9_]{5,32}$/;

const LABEL = 'font-mono text-xs font-medium uppercase tracking-wider text-muted-foreground';
const HINT = 'font-mono text-xs text-muted-foreground';
const VALUE = 'font-mono text-sm tabular-nums';

const STATUS_BADGES: Record<string, 'neon' | 'plasma' | 'amber' | 'crimson' | 'outline'> = {
  authorized: 'neon',
  code_requested: 'plasma',
  password_required: 'amber',
  not_started: 'outline',
  error: 'crimson',
  revoked: 'crimson',
};

function apiErrorMessage(error: unknown, fallback: string): string {
  const message = (error as ApiError | undefined)?.message;
  return typeof message === 'string' && message ? message : fallback;
}

function normalizeUsername(value: string): string {
  const trimmed = value.trim();
  return trimmed.startsWith('@') ? trimmed.slice(1) : trimmed;
}

function usernameProblem(value: string): string | null {
  if (!value) return 'Введите имя';
  if (!USERNAME_PATTERN.test(value)) {
    return 'Нужны 5-32 символа: латинские буквы, цифры и подчёркивание';
  }
  return null;
}

export function TelegramAccountSettings({
  session,
  agentId,
}: {
  session: TelegramSessionRow;
  agentId: string;
}) {
  return (
    <div className="flex flex-col gap-6">
      <dl className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-6">
          <dt className={LABEL}>Статус авторизации</dt>
          <dd>
            <Badge
              // eslint-disable-next-line security/detect-object-injection -- ключ из фиксированного словаря
              variant={STATUS_BADGES[session.authorization_status] ?? 'outline'}
            >
              {session.authorization_status.toUpperCase()}
            </Badge>
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-6">
          <dt className={LABEL}>Номер телефона</dt>
          <dd className={VALUE}>{maskPhoneNumber(session.phone_number)}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-6">
          <dt className={LABEL}>Последняя авторизация</dt>
          <dd className={VALUE}>
            {session.last_authorized_at
              ? formatDistanceToNow(new Date(session.last_authorized_at), {
                  addSuffix: true,
                  locale: ru,
                })
              : '—'}
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-6">
          <dt className={LABEL}>Последняя ошибка</dt>
          <dd className={session.last_error ? `${VALUE} text-destructive` : `${VALUE} text-muted-foreground`}>
            {session.last_error ?? '—'}
          </dd>
        </div>
      </dl>

      <Separator />

      <UsernameField agentId={agentId} username={formatTelegramUsername(session.username)} />
      <PasswordField agentId={agentId} />
    </div>
  );
}

function UsernameField({ agentId, username }: { agentId: string; username: string | null }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(username ?? '');
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (dirty && value !== (username ?? '')) return;
    setDirty(false);
    setValue(username ?? '');
  }, [username, dirty, value]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const normalized = normalizeUsername(value);
    const problem = usernameProblem(normalized);
    if (problem) {
      setError(problem);
      setNotice(null);
      return;
    }
    setError(null);
    setNotice(null);
    setSaving(true);
    try {
      const result = await agentsApi.changeTelegramUsername(agentId, { username: normalized });
      setValue(result.username);
      setNotice(`Сохранено: @${result.username}`);
      queryClient.setQueryData<TelegramSessionRow | null>(
        queryKeys.telegram.byAgent(agentId),
        (previous) => (previous ? { ...previous, username: result.username } : previous),
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.telegram.byAgent(agentId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.agents.all }),
      ]);
    } catch (failure: unknown) {
      setError(apiErrorMessage(failure, 'Не удалось изменить имя. Попробуйте ещё раз.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel className={LABEL} htmlFor="telegram-username">
        Юзернейм
      </FieldLabel>
      <form className="flex flex-col gap-2" onSubmit={(event) => void submit(event)}>
        <div className="flex w-full items-start gap-2">
          <div className="flex-1">
            <Input
              id="telegram-username"
              value={value}
              onChange={(event) => {
                setValue(event.target.value);
                setDirty(true);
                setError(null);
                setNotice(null);
              }}
              placeholder="mimic_account"
              autoComplete="off"
              spellCheck={false}
              disabled={saving}
              aria-invalid={Boolean(error)}
            />
          </div>
          <Button type="submit" isLoading={saving} disabled={!dirty || saving}>
            Сохранить
          </Button>
        </div>
        {error ? (
          <FieldError className="font-mono text-xs">{error}</FieldError>
        ) : (
          <FieldDescription className={HINT}>
            Публичное имя, по которому аккаунт находят в Telegram. 5-32 символа: латинские буквы,
            цифры и подчёркивание.
          </FieldDescription>
        )}
        {notice && <p className="font-mono text-xs text-success">{notice}</p>}
      </form>
    </Field>
  );
}

function PasswordField({ agentId }: { agentId: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const { data, error: stateError, isLoading, refetch } = useTelegramPasswordState(agentId, open);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<{ current?: string; next?: string }>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const close = () => {
    setCurrentPassword('');
    setNewPassword('');
    setFieldErrors({});
    setError(null);
    setNotice(null);
    setOpen(false);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const needsCurrent = data?.has_password === true;
    const problems: { current?: string; next?: string } = {};
    if (needsCurrent && !currentPassword) {
      problems.current = 'Введите текущий пароль';
    }
    if (!newPassword.trim()) {
      problems.next = 'Введите новый пароль';
    }
    setFieldErrors(problems);
    if (Object.keys(problems).length > 0) {
      setError(null);
      return;
    }
    setError(null);
    setNotice(null);
    setSaving(true);
    try {
      await agentsApi.changeTelegramPassword(agentId, {
        ...(needsCurrent ? { current_password: currentPassword } : {}),
        new_password: newPassword,
      });
      setCurrentPassword('');
      setNewPassword('');
      queryClient.setQueryData(queryKeys.telegram.password(agentId), { has_password: true });
      setNotice(needsCurrent ? 'Пароль изменён' : 'Пароль установлен');
    } catch (failure: unknown) {
      setError(apiErrorMessage(failure, 'Не удалось изменить пароль. Попробуйте ещё раз.'));
    } finally {
      setSaving(false);
    }
  };

  const stateErrorMessage = stateError
    ? apiErrorMessage(stateError, 'Не удалось узнать состояние облачного пароля.')
    : null;
  const stateErrorStatus = (stateError as ApiError | null)?.status;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-6">
        <span className={LABEL}>Облачный пароль</span>
        {open ? (
          <Button type="button" variant="ghost" size="sm" onClick={close} disabled={saving}>
            Свернуть
          </Button>
        ) : (
          <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
            Настроить
          </Button>
        )}
      </div>
      <p className={HINT}>
        Пароль, который Telegram спрашивает при входе в аккаунт. Посмотреть или восстановить
        существующий отсюда нельзя.
      </p>

      {open &&
        (stateErrorMessage ? (
          <div className="flex flex-wrap items-center gap-2">
            <FieldError className="font-mono text-xs">{stateErrorMessage}</FieldError>
            <Button type="button" variant="outline" size="sm" onClick={() => void refetch()}>
              Повторить
            </Button>
            {stateErrorStatus === 428 && (
              <Link
                href={`/agent/${agentId}/rebind`}
                className={buttonVariants({ variant: 'outline', size: 'sm' })}
              >
                Перепривязать Telegram
              </Link>
            )}
          </div>
        ) : isLoading || !data ? (
          <p className={HINT}>Проверяем состояние облачного пароля…</p>
        ) : (
          <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)}>
            <FieldGroup>
              {data.has_password && (
                <Field data-invalid={Boolean(fieldErrors.current)}>
                  <FieldLabel className={LABEL} htmlFor="telegram-current-password">
                    Текущий пароль
                  </FieldLabel>
                  <Input
                    id="telegram-current-password"
                    type="password"
                    autoComplete="current-password"
                    value={currentPassword}
                    onChange={(event) => {
                      setCurrentPassword(event.target.value);
                      setFieldErrors((prev) => ({ ...prev, current: undefined }));
                      setError(null);
                    }}
                    disabled={saving}
                    aria-invalid={Boolean(fieldErrors.current)}
                  />
                  {fieldErrors.current && (
                    <FieldError className="font-mono text-xs">{fieldErrors.current}</FieldError>
                  )}
                </Field>
              )}

              <Field data-invalid={Boolean(fieldErrors.next)}>
                <FieldLabel className={LABEL} htmlFor="telegram-new-password">
                  {data.has_password ? 'Новый пароль' : 'Пароль'}
                </FieldLabel>
                <Input
                  id="telegram-new-password"
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(event) => {
                    setNewPassword(event.target.value);
                    setFieldErrors((prev) => ({ ...prev, next: undefined }));
                    setError(null);
                  }}
                  disabled={saving}
                  aria-invalid={Boolean(fieldErrors.next)}
                />
                {fieldErrors.next ? (
                  <FieldError className="font-mono text-xs">{fieldErrors.next}</FieldError>
                ) : (
                  <FieldDescription className={HINT}>
                    Telegram будет спрашивать этот пароль при входе в аккаунт.
                  </FieldDescription>
                )}
              </Field>
            </FieldGroup>

            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" isLoading={saving}>
                {data.has_password ? 'Сменить пароль' : 'Установить пароль'}
              </Button>
              {error && <FieldError className="font-mono text-xs">{error}</FieldError>}
              {notice && <p className="font-mono text-xs text-success">{notice}</p>}
            </div>
          </form>
        ))}
    </div>
  );
}
