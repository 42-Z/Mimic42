'use client';

import { useRef, useState } from 'react';
import { ImagePlus, Loader2, Plus, Trash2, X } from 'lucide-react';

import { agentsApi } from '@/lib/api';
import { useMediaUrl } from '@/hooks/useMediaUrl';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/input';
import { Card } from '@/components/ui/card';
import { useToast } from '@/components/ui/toast';
import { cn } from '@/lib/utils';
import {
  FIRST_COMMENT_MAX_CAPTION,
  FIRST_COMMENT_MAX_TEXT,
  FIRST_COMMENT_MAX_VARIANTS,
} from '@/lib/validators';
import type { ApiError, FirstCommentSettings, FirstCommentVariant } from '@/types';

export const EMPTY_FIRST_COMMENT: FirstCommentSettings = { enabled: false, variants: [] };

const ACCEPTED_IMAGE_TYPES = 'image/jpeg,image/png';

/**
 * Прочитать настройку из нетипизированной JSON-колонки `agents.settings`.
 *
 * Форма могла остаться от прежней версии или быть отредактирована руками,
 * поэтому чужая форма даёт выключенную настройку, а не падение формы —
 * ровно как parse_first_comment на бэкенде.
 */
export function readFirstComment(settings: Record<string, unknown> | null | undefined) {
  const raw = settings?.['first_comment'];
  if (typeof raw !== 'object' || raw === null) return EMPTY_FIRST_COMMENT;

  const source = raw as { enabled?: unknown; variants?: unknown };
  const variants = Array.isArray(source.variants) ? source.variants : [];

  return {
    enabled: source.enabled === true,
    variants: variants.flatMap((item): FirstCommentVariant[] => {
      if (typeof item !== 'object' || item === null) return [];
      const entry = item as { text?: unknown; image_path?: unknown; image_name?: unknown };
      return [
        {
          text: typeof entry.text === 'string' ? entry.text : '',
          image_path: typeof entry.image_path === 'string' ? entry.image_path : null,
          image_name: typeof entry.image_name === 'string' ? entry.image_name : null,
        },
      ];
    }),
  } satisfies FirstCommentSettings;
}

interface FirstCommentSettingsProps {
  agentId: string;
  value: FirstCommentSettings;
  onChange: (next: FirstCommentSettings) => void;
  error?: string;
}

/**
 * Настройка мгновенного комментария под новым постом канала.
 *
 * Вариант без текста и без картинки бэкенд молча отбрасывает, поэтому
 * пустые варианты подсвечиваются здесь, до сохранения.
 */
export function FirstCommentSettingsSection({
  agentId,
  value,
  onChange,
  error,
}: FirstCommentSettingsProps) {
  const setVariant = (index: number, variant: FirstCommentVariant) => {
    onChange({
      ...value,
      variants: value.variants.map((item, i) => (i === index ? variant : item)),
    });
  };

  const removeVariant = (index: number) => {
    onChange({ ...value, variants: value.variants.filter((_, i) => i !== index) });
  };

  const addVariant = () => {
    onChange({
      ...value,
      variants: [...value.variants, { text: '', image_path: null, image_name: null }],
    });
  };

  const atLimit = value.variants.length >= FIRST_COMMENT_MAX_VARIANTS;

  return (
    <Card variant="bordered" padding="md" className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h3 className="font-mono text-sm font-medium text-void-200 uppercase tracking-wider">
            Первый комментарий
          </h3>
          <p className="font-mono text-xs text-void-500 max-w-prose">
            Комментарий уходит под новый пост канала сразу, без задержки и без ИИ.
            Если вариантов несколько, для каждого поста берётся случайный.
          </p>
        </div>
        <Toggle
          checked={value.enabled}
          onChange={(enabled) => onChange({ ...value, enabled })}
          label="Первый комментарий"
        />
      </div>

      {value.enabled && (
        <div className="space-y-3">
          {value.variants.length === 0 && (
            <p className="font-mono text-xs text-void-500">
              Пока ни одного варианта — комментировать нечем.
            </p>
          )}

          {value.variants.map((variant, index) => (
            <VariantRow
              key={index}
              agentId={agentId}
              index={index}
              variant={variant}
              onChange={(next) => setVariant(index, next)}
              onRemove={() => removeVariant(index)}
            />
          ))}

          <Button type="button" variant="ghost" size="sm" onClick={addVariant} disabled={atLimit}>
            <Plus className="h-4 w-4" />
            Добавить вариант
          </Button>
          {atLimit && (
            <p className="font-mono text-xs text-void-500">
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
  variant: FirstCommentVariant;
  onChange: (next: FirstCommentVariant) => void;
  onRemove: () => void;
}

function VariantRow({ agentId, index, variant, onChange, onRemove }: VariantRowProps) {
  const { toast } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  // С картинкой текст уезжает подписью, а у неё лимит вчетверо меньше.
  const maxLength = variant.image_path ? FIRST_COMMENT_MAX_CAPTION : FIRST_COMMENT_MAX_TEXT;
  const isEmpty = variant.text.trim().length === 0 && variant.image_path === null;
  const tooLong = variant.text.length > maxLength;

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const uploaded = await agentsApi.uploadMedia(agentId, file);
      onChange({
        ...variant,
        image_path: uploaded.storage_path,
        image_name: uploaded.name,
      });
    } catch (e: unknown) {
      toast((e as ApiError).message ?? 'Не удалось загрузить картинку', 'error');
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  return (
    <div className="rounded-sm border border-void-700 bg-void-900/40 p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs text-void-500 uppercase tracking-wider">
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
        onChange={(e) => onChange({ ...variant, text: e.target.value })}
        placeholder={variant.image_path ? 'Подпись к картинке (необязательно)' : 'Текст комментария'}
        className="min-h-[80px]"
        showCount
        maxLength={maxLength}
        error={
          tooLong
            ? `Не больше ${maxLength} символов`
            : isEmpty
              ? 'Добавьте текст или картинку — иначе вариант не отправится'
              : undefined
        }
      />

      <div className="flex items-center gap-3">
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPTED_IMAGE_TYPES}
          className="sr-only"
          onChange={(e) => void handleFile(e.target.files?.[0])}
        />
        {variant.image_path ? (
          <ImagePreview
            agentId={agentId}
            storagePath={variant.image_path}
            name={variant.image_name}
            onRemove={() => onChange({ ...variant, image_path: null, image_name: null })}
          />
        ) : (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            isLoading={uploading}
            onClick={() => fileInput.current?.click()}
          >
            <ImagePlus className="h-4 w-4" />
            Добавить картинку
          </Button>
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
    <div className="flex items-center gap-3">
      <div
        className={cn(
          'flex h-16 w-16 items-center justify-center overflow-hidden rounded-sm',
          'border border-void-700 bg-void-800'
        )}
      >
        {status === 'loading' && <Loader2 className="h-4 w-4 animate-spin text-void-500" />}
        {status === 'error' && <span className="font-mono text-xs text-crimson-400">✗</span>}
        {status === 'ready' && url && (
          // eslint-disable-next-line @next/next/no-img-element -- blob URL, next/image не применим
          <img src={url} alt={name ?? 'Картинка комментария'} className="h-full w-full object-cover" />
        )}
      </div>
      <div className="flex flex-col gap-1">
        <span className="font-mono text-xs text-void-400 break-all">{name ?? storagePath}</span>
        <button
          type="button"
          onClick={onRemove}
          className="flex w-fit items-center gap-1 font-mono text-xs text-void-500 transition-colors hover:text-crimson-400 focus:outline-none focus:ring-1 focus:ring-crimson-500"
        >
          <X className="h-3 w-3" />
          Убрать
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
