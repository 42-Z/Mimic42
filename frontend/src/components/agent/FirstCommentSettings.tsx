'use client';

import { useRef, useState } from 'react';
import { ImagePlus, Loader2, Plus, Trash2, X } from 'lucide-react';

import { agentsApi } from '@/lib/api';
import { useMediaUrl } from '@/hooks/useMediaUrl';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/input';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import {
  FIRST_COMMENT_MAX_CAPTION,
  FIRST_COMMENT_MAX_IMAGE_BYTES,
  FIRST_COMMENT_MAX_TEXT,
  FIRST_COMMENT_MAX_VARIANTS,
} from '@/lib/validators';
import type { ApiError, FirstCommentVariant } from '@/types';

/**
 * Вариант в форме: к сохраняемым полям добавлен ключ строки.
 *
 * По ключу загрузка картинки находит свой вариант, даже если пока она шла,
 * соседние варианты удалили, а в этом дописали текст. В настройки ключ не
 * попадает: схема zod при разборе формы отбрасывает незнакомые поля.
 */
export type FirstCommentDraftVariant = FirstCommentVariant & { key: string };

export interface FirstCommentDraft {
  enabled: boolean;
  variants: FirstCommentDraftVariant[];
}

export type FirstCommentUpdate = (prev: FirstCommentDraft) => FirstCommentDraft;

export const EMPTY_FIRST_COMMENT: FirstCommentDraft = { enabled: false, variants: [] };

const ACCEPTED_IMAGE_TYPES = ['image/jpeg', 'image/png'];
const MAX_IMAGE_MB = FIRST_COMMENT_MAX_IMAGE_BYTES / (1024 * 1024);

let lastKey = 0;
function nextKey(): string {
  lastKey += 1;
  return `variant-${lastKey}`;
}

function emptyVariant(): FirstCommentDraftVariant {
  return { key: nextKey(), text: '', image_path: null, image_name: null };
}

/**
 * Прочитать настройку из нетипизированной JSON-колонки `agents.settings`.
 *
 * Форма могла остаться от прежней версии или быть отредактирована руками,
 * поэтому чужая форма даёт выключенную настройку, а не падение формы —
 * ровно как parse_first_comment на бэкенде.
 */
export function readFirstComment(
  settings: Record<string, unknown> | null | undefined,
): FirstCommentDraft {
  const raw = settings?.['first_comment'];
  if (typeof raw !== 'object' || raw === null) return EMPTY_FIRST_COMMENT;

  const source = raw as { enabled?: unknown; variants?: unknown };
  const variants = Array.isArray(source.variants) ? source.variants : [];

  return {
    enabled: source.enabled === true,
    variants: variants.flatMap((item): FirstCommentDraftVariant[] => {
      if (typeof item !== 'object' || item === null) return [];
      const entry = item as { text?: unknown; image_path?: unknown; image_name?: unknown };
      return [
        {
          key: nextKey(),
          text: typeof entry.text === 'string' ? entry.text : '',
          image_path: typeof entry.image_path === 'string' ? entry.image_path : null,
          image_name: typeof entry.image_name === 'string' ? entry.image_name : null,
        },
      ];
    }),
  };
}

/** Почему файл не подойдёт — до загрузки, чтобы не гонять лишние мегабайты. */
export function imageProblem(file: File): string | null {
  if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
    return 'Нужна картинка JPEG или PNG — другие форматы Telegram пришлёт файлом';
  }
  if (file.size > FIRST_COMMENT_MAX_IMAGE_BYTES) {
    return `Картинка больше ${MAX_IMAGE_MB} МБ — Telegram не отправит её фотографией`;
  }
  return null;
}

interface FirstCommentSettingsProps {
  agentId: string;
  value: FirstCommentDraft;
  onChange: (update: FirstCommentUpdate) => void;
  error?: string;
}

/**
 * Настройка мгновенного комментария под новым постом канала.
 *
 * Изменения уходят наверх функциями от свежего состояния: загрузка картинки
 * завершается позже ввода, и снимок варианта на её старте устарел бы.
 */
export function FirstCommentSettingsSection({
  agentId,
  value,
  onChange,
  error,
}: FirstCommentSettingsProps) {
  const patchVariant = (key: string, patch: Partial<FirstCommentVariant>) => {
    onChange((prev) => ({
      ...prev,
      // Вариант удалили, пока шла загрузка, — патчить нечего.
      variants: prev.variants.map((item) => (item.key === key ? { ...item, ...patch } : item)),
    }));
  };

  const removeVariant = (key: string) => {
    onChange((prev) => ({ ...prev, variants: prev.variants.filter((item) => item.key !== key) }));
  };

  const addVariant = () => {
    onChange((prev) => ({ ...prev, variants: [...prev.variants, emptyVariant()] }));
  };

  const atLimit = value.variants.length >= FIRST_COMMENT_MAX_VARIANTS;

  return (
    <Card variant="bordered" padding="md" className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <h3 className="font-mono text-sm font-medium text-void-200 uppercase tracking-wider">
            Первый комментарий
          </h3>
          <p className="font-mono text-xs text-void-300 max-w-prose">
            Под новым постом канала с открытыми комментариями агент сразу оставляет комментарий —
            без задержки и без ИИ. Если вариантов несколько, для каждого поста берётся случайный.
          </p>
        </div>
        <Toggle
          checked={value.enabled}
          onChange={(enabled) => onChange((prev) => ({ ...prev, enabled }))}
          label="Первый комментарий"
        />
      </div>

      {value.enabled && (
        <div className="space-y-3">
          {value.variants.length === 0 && (
            <p className="font-mono text-xs text-void-300">
              Пока ни одного варианта — комментировать нечем.
            </p>
          )}

          {value.variants.map((variant, index) => (
            <VariantRow
              key={variant.key}
              agentId={agentId}
              index={index}
              variant={variant}
              showErrors={Boolean(error)}
              onPatch={(patch) => patchVariant(variant.key, patch)}
              onRemove={() => removeVariant(variant.key)}
            />
          ))}

          <Button type="button" variant="ghost" size="sm" onClick={addVariant} disabled={atLimit}>
            <Plus className="h-4 w-4" />
            Добавить вариант
          </Button>
          {atLimit && (
            <p className="font-mono text-xs text-void-300">
              Больше {FIRST_COMMENT_MAX_VARIANTS} вариантов не сохранить.
            </p>
          )}
        </div>
      )}

      {error && (
        <p className="text-xs text-crimson-400 font-mono flex items-center gap-1" role="alert">
          <span aria-hidden="true">✗</span>
          {error}
        </p>
      )}
    </Card>
  );
}

// ── Один вариант ──────────────────────────────────────────────────────────────

interface VariantRowProps {
  agentId: string;
  index: number;
  variant: FirstCommentDraftVariant;
  /** Сохранение не прошло проверку — пустой вариант подсвечивается сразу. */
  showErrors: boolean;
  onPatch: (patch: Partial<FirstCommentVariant>) => void;
  onRemove: () => void;
}

function VariantRow({ agentId, index, variant, showErrors, onPatch, onRemove }: VariantRowProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  // Только что добавленный вариант пуст по определению: ругать его, пока в
  // поле ничего не начинали вводить, рано. Пустой вариант из сохранённых
  // настроек — уже ошибка.
  const [touched, setTouched] = useState(
    () => variant.text.length > 0 || variant.image_path !== null
  );

  // С картинкой текст уезжает подписью, а у неё лимит вчетверо меньше.
  const maxLength = variant.image_path ? FIRST_COMMENT_MAX_CAPTION : FIRST_COMMENT_MAX_TEXT;
  const isEmpty = variant.text.trim().length === 0 && variant.image_path === null;
  const tooLong = variant.text.length > maxLength;
  const errorId = `first-comment-image-error-${variant.key}`;

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    const problem = imageProblem(file);
    setUploadError(problem);
    if (problem) {
      if (fileInput.current) fileInput.current.value = '';
      return;
    }
    setUploading(true);
    try {
      const uploaded = await agentsApi.uploadMedia(agentId, file);
      // Только поля картинки: текст за время загрузки мог измениться.
      onPatch({ image_path: uploaded.storage_path, image_name: uploaded.name });
    } catch (e: unknown) {
      setUploadError((e as ApiError).message ?? 'Не удалось загрузить картинку — попробуйте ещё раз');
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  return (
    <div className="rounded-sm border border-void-700 bg-void-900/40 p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs text-void-300 uppercase tracking-wider">
          Вариант {index + 1}
        </span>
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Удалить вариант ${index + 1}`}
          className="flex h-8 w-8 items-center justify-center rounded-sm text-void-400 transition-colors hover:bg-void-800 hover:text-crimson-400 focus:outline-none focus:ring-1 focus:ring-crimson-500"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <Textarea
        value={variant.text}
        onChange={(e) => onPatch({ text: e.target.value })}
        onBlur={() => setTouched(true)}
        aria-label={`Текст варианта ${index + 1}`}
        placeholder={variant.image_path ? 'Подпись к картинке (необязательно)' : 'Текст комментария'}
        className="min-h-[80px]"
        showCount
        maxLength={maxLength}
        error={
          tooLong
            ? `Не больше ${maxLength} символов`
            : isEmpty && (touched || showErrors)
              ? 'Добавьте текст или картинку — иначе вариант не отправится'
              : undefined
        }
      />

      <div className="space-y-2">
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPTED_IMAGE_TYPES.join(',')}
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(e) => void handleFile(e.target.files?.[0])}
        />
        {variant.image_path ? (
          <ImagePreview
            agentId={agentId}
            storagePath={variant.image_path}
            name={variant.image_name}
            onRemove={() => onPatch({ image_path: null, image_name: null })}
          />
        ) : (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              isLoading={uploading}
              onClick={() => fileInput.current?.click()}
              aria-describedby={uploadError ? errorId : undefined}
            >
              <ImagePlus className="h-4 w-4" />
              {uploading ? 'Загружаем…' : 'Добавить картинку'}
            </Button>
            <span className="font-mono text-xs text-void-300">
              JPEG или PNG до {MAX_IMAGE_MB} МБ
            </span>
          </div>
        )}
        {uploadError && (
          <p
            id={errorId}
            role="alert"
            className="text-xs text-crimson-400 font-mono flex items-center gap-1"
          >
            <span aria-hidden="true">✗</span>
            {uploadError}
          </p>
        )}
      </div>
    </div>
  );
}

// ── Превью картинки ───────────────────────────────────────────────────────────

function ImagePreview({
  agentId,
  storagePath,
  name,
  onRemove,
}: {
  agentId: string;
  storagePath: string;
  name: string | null;
  onRemove: () => void;
}) {
  const { url, status } = useMediaUrl(agentId, storagePath);

  return (
    <div className="flex items-center gap-3 min-w-0">
      <div
        className={cn(
          'flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-sm',
          'border border-void-700 bg-void-800'
        )}
      >
        {status === 'loading' && <Loader2 className="h-4 w-4 animate-spin text-void-300" />}
        {status === 'error' && (
          <span className="font-mono text-[10px] text-crimson-400 text-center px-1">
            не открылась
          </span>
        )}
        {status === 'ready' && url && (
          // eslint-disable-next-line @next/next/no-img-element -- blob URL, next/image не применим
          <img src={url} alt={name ?? 'Картинка комментария'} className="h-full w-full object-cover" />
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-1">
        <span className="font-mono text-xs text-void-200 break-all">{name ?? storagePath}</span>
        <button
          type="button"
          onClick={onRemove}
          className="flex w-fit items-center gap-1 font-mono text-xs text-void-300 transition-colors hover:text-crimson-400 focus:outline-none focus:ring-1 focus:ring-crimson-500"
        >
          <X className="h-3 w-3" />
          Убрать картинку
        </button>
      </div>
    </div>
  );
}

// ── Переключатель ─────────────────────────────────────────────────────────────

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors',
        'focus:outline-none focus:ring-1 focus:ring-plasma-500',
        checked ? 'border-plasma-600 bg-plasma-700' : 'border-void-600 bg-void-700'
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'inline-block h-4 w-4 rounded-full bg-void-100 transition-transform',
          checked ? 'translate-x-6' : 'translate-x-1'
        )}
      />
    </button>
  );
}
