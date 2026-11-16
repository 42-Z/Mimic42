'use client';

import { useState } from 'react';
import type { ComponentType } from 'react';
import type { ZodIssue } from 'zod';
import {
  AlertTriangle,
  Clock,
  Gauge,
  ImagePlus,
  MessageSquare,
  Play,
  Save,
  Target,
  Users,
} from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  ATTACK_CAPTION_MAX,
  ATTACK_TEXT_MAX,
  ATTACK_TITLE_MAX,
  type AttackEditFormState,
  type AttackFormState,
} from '@/lib/attacks/types';
import { attackCreateSchema, attackEditSchema } from '@/lib/attacks/validators';
import { attackPace } from '@/lib/attacks/display';
import { AttackImageUploader } from './AttackImageUploader';
import { AttackLimitFields } from './AttackLimitFields';
import { AttackMimicPicker } from './AttackMimicPicker';
import { AttackTextList } from './AttackTextList';
import type {
  AttackAgentAvailability,
  AttackDraft,
  AttackLimitKind,
  AttackPatch,
} from '@/types';

const EMPTY_FORM: AttackFormState = {
  title: '',
  target_link: '',
  texts: [''],
  images: [],
  limit_kind: 'messages',
  message_limit: null,
  duration_minutes: null,
  agent_ids: [],
};

export interface AttackFormProps {
  mode: 'create' | 'edit';
  agents?: AttackAgentAvailability[];
  agentsLoading?: boolean;
  targetLink?: string;
  initial?: AttackFormState;
  editInitial?: AttackEditFormState;
  slowmodeSeconds?: number | null;
  sentCount?: number;
  submitting?: 'draft' | 'start' | 'save' | null;
  onCreate?: (draft: AttackDraft, intent: 'draft' | 'start') => void;
  onUpdate?: (patch: AttackPatch) => void;
  onCancel?: () => void;
}

function initialFormState({
  mode,
  initial,
  editInitial,
  targetLink,
}: Pick<AttackFormProps, 'mode' | 'initial' | 'editInitial' | 'targetLink'>): AttackFormState {
  if (mode === 'edit' && editInitial) {
    return {
      title: editInitial.title,
      target_link: targetLink ?? '',
      texts: editInitial.texts.length > 0 ? [...editInitial.texts] : [''],
      images: [...editInitial.images],
      limit_kind: editInitial.limit_kind,
      message_limit: editInitial.message_limit,
      duration_minutes: editInitial.duration_minutes,
      agent_ids: [],
    };
  }

  const source = initial ?? EMPTY_FORM;
  return {
    ...source,
    texts: source.texts.length > 0 ? [...source.texts] : [''],
    images: [...source.images],
    agent_ids: [...source.agent_ids],
  };
}

function SectionHeader({
  icon: Icon,
  title,
  description,
}: {
  icon: ComponentType<{ className?: string }>;
  title: string;
  description?: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-sm border border-border bg-muted">
        <Icon className="size-4 text-primary" />
      </span>
      <div>
        <h2 className="font-mono text-sm font-semibold uppercase tracking-wider text-foreground">
          {title}
        </h2>
        {description && (
          <p className="mt-0.5 font-mono text-[11px] leading-snug text-muted-foreground">
            {description}
          </p>
        )}
      </div>
    </div>
  );
}

export function AttackForm({
  mode,
  agents = [],
  agentsLoading = false,
  targetLink,
  initial,
  editInitial,
  slowmodeSeconds,
  sentCount = 0,
  submitting = null,
  onCreate,
  onUpdate,
  onCancel,
}: AttackFormProps) {
  const [state, setState] = useState<AttackFormState>(() =>
    initialFormState({ mode, initial, editInitial, targetLink }),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});

  const textMax = state.images.length > 0 ? ATTACK_CAPTION_MAX : ATTACK_TEXT_MAX;
  const pace = attackPace(slowmodeSeconds);
  const limitValue =
    state.limit_kind === 'messages' ? state.message_limit : state.duration_minutes;
  const limitError =
    errors['message_limit'] ?? errors['duration_minutes'] ?? errors['limit'];
  const limitBelowSent =
    mode === 'edit' &&
    state.limit_kind === 'messages' &&
    state.message_limit !== null &&
    sentCount > 0 &&
    state.message_limit < sentCount;

  const clearError = (key: string) => {
    setErrors((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      // eslint-disable-next-line security/detect-object-injection -- keys are field names set by this form
      delete next[key];
      return next;
    });
  };

  const patchState = (next: Partial<AttackFormState>) => {
    setState((prev) => ({ ...prev, ...next }));
  };

  const setKind = (kind: AttackLimitKind) => {
    setState((prev) => ({
      ...prev,
      limit_kind: kind,
      message_limit: kind === 'messages' ? prev.message_limit : null,
      duration_minutes: kind === 'minutes' ? prev.duration_minutes : null,
    }));
    clearError('message_limit');
    clearError('duration_minutes');
  };

  const setLimitValue = (value: number | null) => {
    setState((prev) =>
      prev.limit_kind === 'messages'
        ? { ...prev, message_limit: value, duration_minutes: null }
        : { ...prev, duration_minutes: value, message_limit: null },
    );
    clearError('message_limit');
    clearError('duration_minutes');
  };

  const setText = (index: number, value: string) => {
    setState((prev) => ({
      ...prev,
      texts: prev.texts.map((text, item) => (item === index ? value : text)),
    }));
    clearError(`texts.${index}`);
  };

  const addText = () => {
    setState((prev) => ({ ...prev, texts: [...prev.texts, ''] }));
  };

  const removeText = (index: number) => {
    setState((prev) => ({
      ...prev,
      texts: prev.texts.filter((_, item) => item !== index),
    }));
    setErrors((prev) => {
      const next = { ...prev };
      delete next[`texts.${index}`];
      return next;
    });
  };

  const applyErrors = (issues: ZodIssue[]) => {
    const next: Record<string, string> = {};
    for (const issue of issues) {
      const key = issue.path.length > 0 ? issue.path.join('.') : '_form';
      // eslint-disable-next-line security/detect-object-injection -- keys are Zod field paths
      if (!next[key]) next[key] = issue.message;
    }
    setErrors(next);
  };

  const submitCreate = (intent: 'draft' | 'start') => {
    if (intent === 'start' && state.agent_ids.length === 0) {
      setErrors({ agent_ids: 'Добавьте хотя бы одного мимика, чтобы запустить атаку' });
      return;
    }
    const result = attackCreateSchema.safeParse(state);
    if (!result.success) {
      applyErrors(result.error.issues);
      return;
    }
    setErrors({});
    onCreate?.(result.data, intent);
  };

  const submitEdit = () => {
    const result = attackEditSchema.safeParse({
      ...state,
      version: editInitial?.version,
    });
    if (!result.success) {
      applyErrors(result.error.issues);
      return;
    }
    setErrors({});
    onUpdate?.(result.data);
  };

  /* eslint-disable security/detect-object-injection -- field errors keyed by form paths */
  const displayErrors = { ...errors };
  state.texts.forEach((text, index) => {
    const key = `texts.${index}`;
    if (!displayErrors[key] && Array.from(text).length > textMax) {
      displayErrors[key] =
        textMax === ATTACK_CAPTION_MAX
          ? `С картинками текст не длиннее ${ATTACK_CAPTION_MAX} символов`
          : `Текст не длиннее ${ATTACK_TEXT_MAX} символов`;
    }
  });
  /* eslint-enable security/detect-object-injection */

  const canStart = state.agent_ids.length > 0;

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => event.preventDefault()}
      noValidate
    >
      {errors['_form'] && (
        <Alert variant="destructive">
          <AlertTriangle aria-hidden="true" />
          <AlertTitle>Форма не сохранилась</AlertTitle>
          <AlertDescription>{errors['_form']}</AlertDescription>
        </Alert>
      )}

      <Card variant="glass" padding="md" className="flex flex-col gap-5">
        <SectionHeader
          icon={Target}
          title="Цель"
          description="Один пост канала на всю атаку. Комментарии уйдут в обсуждение ответом на него."
        />
        {mode === 'create' ? (
          <Input
            label="Ссылка на пост"
            placeholder="https://t.me/канал/123"
            value={state.target_link}
            onChange={(event) => {
              patchState({ target_link: event.target.value });
              clearError('target_link');
            }}
            error={displayErrors['target_link']}
            hint="Публичная или приватная ссылка t.me на конкретный пост."
          />
        ) : (
          <Input
            label="Ссылка на пост"
            value={targetLink ?? state.target_link}
            disabled
            hint="Ссылку изменить нельзя: атака привязана к этому посту."
          />
        )}
        <Input
          label="Название"
          placeholder="Например, «Розыгрыш»"
          value={state.title}
          maxLength={ATTACK_TITLE_MAX}
          onChange={(event) => {
            patchState({ title: event.target.value });
            clearError('title');
          }}
          error={displayErrors['title']}
          hint="Необязательно. Без названия карточка покажет канал из ссылки."
        />
      </Card>

      <Card variant="glass" padding="md" className="flex flex-col gap-4">
        <SectionHeader
          icon={MessageSquare}
          title="Тексты"
          description={`Каждый комментарий получает один случайный текст. До ${textMax} символов.`}
        />
        <AttackTextList
          texts={state.texts}
          maxLength={textMax}
          errors={displayErrors}
          onChange={setText}
          onAdd={addText}
          onRemove={removeText}
        />
      </Card>

      <Card variant="glass" padding="md" className="flex flex-col gap-4">
        <SectionHeader
          icon={ImagePlus}
          title="Картинки"
          description="Необязательно. Порядок в каждом комментарии перемешивается."
        />
        <AttackImageUploader
          images={state.images}
          onAdd={(uploaded) => {
            setState((prev) => ({ ...prev, images: [...prev.images, ...uploaded] }));
            clearError('images');
          }}
          onRemove={(path) => {
            setState((prev) => ({
              ...prev,
              images: prev.images.filter((image) => image.path !== path),
            }));
            clearError('images');
          }}
          error={displayErrors['images']}
        />
      </Card>

      <Card variant="glass" padding="md" className="flex flex-col gap-4">
        <SectionHeader
          icon={Clock}
          title="Лимит"
          description="Один общий лимит на всю атаку: количество сообщений или длительность."
        />
        <AttackLimitFields
          kind={state.limit_kind}
          value={limitValue}
          error={limitError}
          onKindChange={setKind}
          onValueChange={setLimitValue}
        />

        <div className="flex items-start gap-2 rounded-sm border border-border/70 bg-muted/30 p-3">
          <Gauge className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
          <p className="font-mono text-[11px] leading-relaxed text-muted-foreground">
            <span className="text-foreground">Темп: {pace.label}.</span>{' '}
            Частота не настраивается: мимики сами держат паузу не меньше базы и ждут FloodWait.
            Если у обсуждения есть медленный режим, пауза подстроится под него.
          </p>
        </div>

        {limitBelowSent && (
          <Alert variant="warning">
            <AlertTriangle aria-hidden="true" />
            <AlertTitle>Лимит меньше уже отправленного</AlertTitle>
            <AlertDescription>
              Отправлено {sentCount}. После сохранения атака завершится, потому что новый лимит
              уже достигнут. Счётчик отправленного не обнулится.
            </AlertDescription>
          </Alert>
        )}
      </Card>

      {mode === 'create' && (
        <Card variant="glass" padding="md" className="flex flex-col gap-4">
          <SectionHeader
            icon={Users}
            title="Мимики"
            description="Кто будет писать комментарии. Добавление сразу переносит мимика из другой атаки."
          />
          <AttackMimicPicker
            agents={agents}
            value={state.agent_ids}
            onChange={(agentIds) => {
              patchState({ agent_ids: agentIds });
              clearError('agent_ids');
            }}
            isLoading={agentsLoading}
            error={displayErrors['agent_ids']}
          />
        </Card>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="font-mono text-xs text-muted-foreground">
          {mode === 'create'
            ? 'Черновик можно сохранить без мимиков. Запуск требует хотя бы одного.'
            : 'Изменения применятся после подтверждения. Ссылка и ростер мимиков здесь не меняются.'}
        </p>
        <div className="flex flex-wrap justify-end gap-2">
          {mode === 'edit' && onCancel && (
            <Button type="button" variant="ghost" onClick={onCancel}>
              Отмена
            </Button>
          )}
          {mode === 'create' ? (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={() => submitCreate('draft')}
                isLoading={submitting === 'draft'}
                disabled={submitting !== null}
                leftIcon={<Save className="size-3.5" aria-hidden="true" />}
              >
                Сохранить черновик
              </Button>
              <Button
                type="button"
                onClick={() => submitCreate('start')}
                isLoading={submitting === 'start'}
                disabled={!canStart || submitting !== null}
                title={canStart ? undefined : 'Добавьте хотя бы одного мимика'}
                leftIcon={<Play className="size-3.5" aria-hidden="true" />}
              >
                Создать и запустить
              </Button>
            </>
          ) : (
            <Button
              type="button"
              onClick={submitEdit}
              isLoading={submitting === 'save'}
              leftIcon={<Save className="size-3.5" aria-hidden="true" />}
            >
              Сохранить изменения
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}
