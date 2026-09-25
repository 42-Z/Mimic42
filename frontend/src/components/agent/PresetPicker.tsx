'use client';

import { useState } from 'react';
import { Sparkles } from 'lucide-react';
import { Modal } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/card';
import { usePromptPresets } from '@/hooks/usePromptPresets';
import { cn } from '@/lib/utils';
import type { PromptPresetRow } from '@/types';

export function PresetPicker({
  currentValue,
  onApply,
}: {
  currentValue: string;
  onApply: (body: string) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const { data, isLoading, isError } = usePromptPresets();

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        leftIcon={<Sparkles className="h-3.5 w-3.5" />}
        onClick={() => setIsOpen(true)}
        data-testid="open-presets"
      >
        Пресеты
      </Button>

      <PresetPickerDialog
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        presets={data ?? []}
        isLoading={isLoading}
        isError={isError}
        currentValue={currentValue}
        onApply={(body) => {
          onApply(body);
          setIsOpen(false);
        }}
      />
    </>
  );
}

export function PresetPickerDialog({
  isOpen,
  onClose,
  presets,
  isLoading,
  isError,
  currentValue,
  onApply,
}: {
  isOpen: boolean;
  onClose: () => void;
  presets: PromptPresetRow[];
  isLoading: boolean;
  isError: boolean;
  currentValue: string;
  onApply: (body: string) => void;
}) {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  // Вторая стадия кнопки вместо вложенного диалога: Modal рендерится инлайном
  // и держит один жёсткий id заголовка, два вложенных сломали бы фокус и ARIA.
  const [confirming, setConfirming] = useState(false);

  const selected = presets.find((preset) => preset.slug === selectedSlug) ?? presets[0] ?? null;
  const willOverwrite = currentValue.trim().length > 0;

  const handleClose = () => {
    setConfirming(false);
    onClose();
  };

  const handleSelect = (slug: string) => {
    setSelectedSlug(slug);
    setConfirming(false);
  };

  const handleApply = () => {
    if (!selected) return;
    if (willOverwrite && !confirming) {
      setConfirming(true);
      return;
    }
    setConfirming(false);
    onApply(selected.body);
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title="Пресеты промптов"
      size="xl"
      className="max-w-3xl"
    >
      {isLoading && <Skeleton className="h-64 w-full" />}

      {!isLoading && isError && (
        <p role="alert" className="font-mono text-xs text-crimson-400">
          Не удалось загрузить пресеты
        </p>
      )}

      {!isLoading && !isError && presets.length === 0 && (
        <p className="font-mono text-xs text-void-400">Пресетов пока нет</p>
      )}

      {!isLoading && !isError && presets.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
          <div
            role="listbox"
            aria-label="Пресеты"
            className="flex max-h-72 flex-col gap-1 overflow-y-auto"
          >
            {presets.map((preset) => (
              <button
                key={preset.slug}
                type="button"
                role="option"
                aria-selected={selected?.slug === preset.slug}
                onClick={() => handleSelect(preset.slug)}
                className={cn(
                  'rounded-sm border px-3 py-2 text-left transition-colors duration-150',
                  selected?.slug === preset.slug
                    ? 'border-plasma-600 bg-plasma-950/40'
                    : 'border-void-700 hover:border-void-500',
                )}
              >
                <span className="block font-mono text-xs text-void-100">{preset.title}</span>
                <span className="block font-mono text-[11px] text-void-300">{preset.summary}</span>
              </button>
            ))}
          </div>

          <pre
            data-testid="preset-body"
            className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-sm border border-void-700 bg-void-900 p-3 font-mono text-xs text-void-300"
          >
            {selected?.body}
          </pre>
        </div>
      )}

      <div className="mt-6 flex items-center justify-end gap-3">
        {confirming && (
          <span role="alert" className="mr-auto font-mono text-xs text-amber-400">
            Текущий характер будет заменён
          </span>
        )}
        <Button type="button" variant="ghost" size="sm" onClick={handleClose}>
          Отмена
        </Button>
        <Button type="button" size="sm" onClick={handleApply} disabled={!selected}>
          {confirming ? 'Всё равно заменить' : 'Применить пресет'}
        </Button>
      </div>
    </Modal>
  );
}
