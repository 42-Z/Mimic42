'use client';

import { useEffect, useRef, useState } from 'react';
import { Eye, EyeOff, KeyRound, ShieldCheck } from 'lucide-react';
import { useAdminActions, useAdminTelegramSettings } from '@/hooks/useAdmin';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/card';
import { useToast } from '@/components/ui/toast';

const TELEGRAM_API_ID_MAX = 2_147_483_647;

function parseTelegramApiId(value: string): number | null {
  const normalized = value.trim();
  if (!/^\d+$/.test(normalized)) return null;
  const parsed = Number(normalized);
  return Number.isSafeInteger(parsed) && parsed >= 1 && parsed <= TELEGRAM_API_ID_MAX
    ? parsed
    : null;
}

function sourceLabel(source: 'database' | 'unconfigured'): string {
  if (source === 'database') return 'Настройка платформы';
  return 'Не настроено';
}

export function AdminTelegramSettings() {
  const settingsQuery = useAdminTelegramSettings();
  const { saveTelegramSettings } = useAdminActions();
  const { toast } = useToast();
  const [apiId, setApiId] = useState('');
  const [apiIdTouched, setApiIdTouched] = useState(false);
  const [apiHash, setApiHash] = useState('');
  const [showApiHash, setShowApiHash] = useState(false);
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const apiIdDirty = useRef(false);
  const apiHashDirty = useRef(false);

  useEffect(() => {
    const serverApiId = settingsQuery.data?.api_id;
    if (serverApiId === undefined || apiIdDirty.current) return;
    setApiId(serverApiId === null ? '' : String(serverApiId));
  }, [settingsQuery.data?.api_id]);

  useEffect(() => {
    const serverApiHash = settingsQuery.data?.api_hash;
    if (serverApiHash === undefined || apiHashDirty.current) return;
    setApiHash(serverApiHash ?? '');
  }, [settingsQuery.data?.api_hash]);

  const parsedApiId = parseTelegramApiId(apiId);
  const apiIdError = !apiIdTouched
    ? undefined
    : apiId.trim().length === 0
      ? 'Укажи API ID.'
      : parsedApiId === null
        ? `Введи целое число от 1 до ${TELEGRAM_API_ID_MAX}.`
        : undefined;
  const canSave =
    parsedApiId !== null && apiHash.trim().length > 0 && !saving && !settingsQuery.isLoading;

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const apiIdValue = parseTelegramApiId(apiId);
    const apiHashValue = apiHash.trim();
    if (apiIdValue === null || apiHashValue.length === 0 || saving) return;

    setSaving(true);
    setSubmitError(null);
    try {
      const saved = await saveTelegramSettings({ api_id: apiIdValue, api_hash: apiHashValue });
      apiIdDirty.current = false;
      apiHashDirty.current = false;
      setApiId(saved.api_id === null ? String(apiIdValue) : String(saved.api_id));
      setApiHash(saved.api_hash ?? apiHashValue);
      toast('Настройки Telegram сохранены.', 'success');
    } catch {
      setSubmitError('Не удалось сохранить настройки. Проверь данные и попробуй снова.');
    } finally {
      setSaving(false);
    }
  };

  if (settingsQuery.isLoading) {
    return (
      <section aria-label="Загружаем настройки Telegram" aria-busy="true" className="max-w-2xl space-y-4" role="status">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-10 w-full" />
      </section>
    );
  }

  if (settingsQuery.isError || !settingsQuery.data) {
    return (
      <Alert className="max-w-2xl" variant="destructive">
        <KeyRound aria-hidden="true" />
        <div className="min-w-0">
          <AlertTitle>Не удалось загрузить настройки Telegram</AlertTitle>
          <AlertDescription>Настройки временно недоступны. Повтори запрос.</AlertDescription>
          <Button
            className="mt-4"
            onClick={() => void settingsQuery.refetch()}
            size="sm"
            variant="outline"
          >
            Повторить
          </Button>
        </div>
      </Alert>
    );
  }

  const settings = settingsQuery.data;

  return (
    <section aria-labelledby="admin-telegram-title" className="max-w-2xl space-y-6">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h2
            className="font-display text-xl font-semibold tracking-tight text-foreground"
            id="admin-telegram-title"
          >
            Общая пара Telegram
          </h2>
          <Badge variant={settings.source === 'unconfigured' ? 'outline' : 'secondary'}>
            {sourceLabel(settings.source)}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          {settings.api_hash
            ? 'Сохранённый HASH подставлен в поле — его можно скрыть или заменить.'
            : settings.has_api_hash
              ? 'HASH сохранён, но недоступен для показа. Введи его заново, чтобы заменить пару.'
              : 'Общая пара ещё не настроена.'}
        </p>
      </header>

      <form className="space-y-5" onSubmit={(event) => void handleSubmit(event)}>
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="platform-api-id">API ID</FieldLabel>
            <Input
              autoComplete="off"
              disabled={saving}
              error={apiIdError}
              id="platform-api-id"
              inputMode="numeric"
              maxLength={10}
              onBlur={() => setApiIdTouched(true)}
              onChange={(event) => {
                apiIdDirty.current = true;
                setApiIdTouched(true);
                setApiId(event.target.value);
                setSubmitError(null);
              }}
              placeholder="Например, 12345678"
              required
              type="text"
              value={apiId}
            />
            <FieldDescription>Числовой идентификатор приложения Telegram.</FieldDescription>
          </Field>

          <Field>
            <FieldLabel htmlFor="platform-api-hash">API HASH</FieldLabel>
            <Input
              autoComplete="off"
              disabled={saving}
              id="platform-api-hash"
              onChange={(event) => {
                apiHashDirty.current = true;
                setApiHash(event.target.value);
                setSubmitError(null);
              }}
              placeholder="Введи API HASH"
              required
              rightElement={
                <Button
                  aria-label={showApiHash ? 'Скрыть HASH' : 'Показать HASH'}
                  onClick={() => setShowApiHash((value) => !value)}
                  size="icon-sm"
                  type="button"
                  variant="ghost"
                >
                  {showApiHash ? (
                    <EyeOff aria-hidden="true" className="h-4 w-4" />
                  ) : (
                    <Eye aria-hidden="true" className="h-4 w-4" />
                  )}
                </Button>
              }
              type={showApiHash ? 'text' : 'password'}
              value={apiHash}
            />
            <FieldDescription>
              HASH сохранённой пары. Введи новое значение, чтобы заменить его.
            </FieldDescription>
          </Field>
        </FieldGroup>

        {submitError && (
          <Alert variant="destructive">
            <AlertTitle>Настройки не сохранены</AlertTitle>
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}

        <Button disabled={!canSave} isLoading={saving} type="submit">
          <ShieldCheck aria-hidden="true" className="h-4 w-4" />
          {saving ? 'Сохраняю…' : 'Сохранить настройки'}
        </Button>
      </form>

      <p className="border-t border-border pt-4 text-sm leading-relaxed text-muted-foreground">
        Новая пара применяется к новым подключениям. Уже подключённые мимики продолжат работать со
        своей парой.
      </p>
    </section>
  );
}
