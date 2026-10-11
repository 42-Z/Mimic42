'use client';

import { useEffect, useMemo, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { Modal } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/card';
import { usePromptPresets } from '@/hooks/usePromptPresets';
import { usePresetFavorites } from '@/hooks/usePresetFavorites';
import { readEnabledTools } from '@/lib/tools/agentTools';
import { TOOL_INFO } from '@/lib/tools/toolInfo';
import { getSupabaseClient } from '@/lib/supabase/client';
import { cn } from '@/lib/utils';
import type { PromptPresetRow, PresetFavoriteRow } from '@/types';

/**
 * Результат применения пресета: текст характера и сырой частичный патч
 * настроек (может быть `null`, `{}` или нести другие ключи помимо
 * `enabled_tools`). Читать настройки только через `readEnabledTools`.
 */
export interface AppliedPromptPreset {
  body: string;
  settings: Record<string, unknown> | null;
}

/** Запись списка выбора: у избранного тело может отдавать снимок. */
export interface PickerEntry {
  key: string;
  title: string;
  summary: string;
  body: string;
  settings: Record<string, unknown> | null;
  section: 'official' | 'mine' | 'favorites';
}

// Секции списка выбора: заголовок → записи. Пустые секции не рендерятся.
const SECTION_LABELS = {
  official: 'Официальные',
  mine: 'Мои',
  favorites: 'Избранное',
} as const;

export function PresetPicker({
  currentValue,
  onApply,
}: {
  currentValue: string;
  onApply: (preset: AppliedPromptPreset) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const { data, isLoading, isError } = usePromptPresets();
  const { data: favoritesList, isLoading: favoritesLoading } = usePresetFavorites();

  useEffect(() => {
    let cancelled = false;
    getSupabaseClient()
      .auth.getUser()
      .then(({ data }) => {
        if (!cancelled) setUserId(data.user?.id ?? null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
        favorites={favoritesList ?? []}
        userId={userId}
        isLoading={isLoading}
        isLoadingFavorites={favoritesLoading}
        isError={isError}
        currentValue={currentValue}
        onApply={(preset) => {
          onApply(preset);
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
  favorites,
  userId,
  isLoading,
  isLoadingFavorites,
  isError,
  currentValue,
  onApply,
}: {
  isOpen: boolean;
  onClose: () => void;
  presets: PromptPresetRow[];
  favorites: PresetFavoriteRow[];
  userId: string | null;
  isLoading: boolean;
  isLoadingFavorites?: boolean;
  isError: boolean;
  currentValue: string;
  onApply: (preset: AppliedPromptPreset) => void;
}) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  // Вторая стадия кнопки вместо вложенного диалога: Modal рендерится инлайном
  // и держит один жёсткий id заголовка, два вложенных сломали бы фокус и ARIA.
  const [confirming, setConfirming] = useState(false);

  // Единый список выбора: официальные (owner_id пустой), свои. Чужие витринные
  // пресеты без избранного в меню не попадают. Живое избранное (preset_id
  // задан) показывает текущую версию пресета, замороженное — снимок.
  const sections = useMemo(() => {
    const liveById = new Map(presets.map((preset) => [preset.id, preset]));
    const official: PickerEntry[] = [];
    const mine: PickerEntry[] = [];
    for (const preset of presets) {
      if (preset.owner_id !== null && preset.owner_id !== userId) continue;
      const entry: PickerEntry = {
        key: `preset:${preset.id}`,
        title: preset.title,
        summary: preset.summary,
        body: preset.body,
        settings: preset.settings,
        section: preset.owner_id === null ? 'official' : 'mine',
      };
      if (preset.owner_id === null) official.push(entry);
      else mine.push(entry);
    }
    mine.sort((a, b) => a.title.localeCompare(b.title, 'ru'));
    const favoritesSection: PickerEntry[] = favorites.map((favorite) => {
      const source = favorite.preset_id ? liveById.get(favorite.preset_id) : undefined;
      return {
        key: `fav:${favorite.id}`,
        title: source?.title ?? favorite.frozen_title ?? 'Без названия',
        summary: source?.summary ?? favorite.frozen_summary ?? '',
        body: source ? source.body : favorite.frozen_body ?? '',
        settings: source ? source.settings : favorite.frozen_settings,
        section: 'favorites' as const,
      };
    });
    return { official, mine, favorites: favoritesSection };
  }, [presets, favorites, userId]);

  const flat = useMemo(
    () => [...sections.official, ...sections.mine, ...sections.favorites],
    [sections],
  );

  const selected = flat.find((entry) => entry.key === selectedKey) ?? flat[0] ?? null;
  const willOverwrite = currentValue.trim().length > 0;
  const selectedTools = selected ? readEnabledTools(selected.settings) : null;

  const handleClose = () => {
    setConfirming(false);
    onClose();
  };

  const handleSelect = (key: string) => {
    setSelectedKey(key);
    setConfirming(false);
  };

  const handleApply = () => {
    if (!selected) return;
    if (willOverwrite && !confirming) {
      setConfirming(true);
      return;
    }
    setConfirming(false);
    onApply({ body: selected.body, settings: selected.settings ?? null });
  };

  const sectionEntries: [keyof typeof SECTION_LABELS, PickerEntry[]][] = [
    ['official', sections.official],
    ['mine', sections.mine],
    ['favorites', sections.favorites],
  ];
  const favoritesPending = isLoadingFavorites === true && !isError && !isLoading;

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

      {!isLoading && !isError && flat.length === 0 && !favoritesPending && (
        <p className="font-mono text-xs text-muted-foreground">Пресетов пока нет</p>
      )}

      {!isLoading && !isError && flat.length === 0 && favoritesPending && (
        <Skeleton className="h-40 w-full" />
      )}

      {!isLoading && !isError && flat.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
          <div
            role="listbox"
            aria-label="Пресеты"
            className="flex max-h-72 flex-col gap-1 overflow-y-auto"
          >
            {sectionEntries.map(([section, entries]) =>
              entries.length === 0 ? null : (
                <div key={section} data-testid={`picker-section-${section}`}>
                  <p className="px-3 pb-1 pt-2 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    {/* eslint-disable-next-line security/detect-object-injection -- section is a typed union, not user input */}
                    {SECTION_LABELS[section]}
                  </p>                  {entries.map((entry) => (
                    <button
                      key={entry.key}
                      type="button"
                      role="option"
                      aria-selected={selected?.key === entry.key}
                      onClick={() => handleSelect(entry.key)}
                      className={cn(
                        'rounded-sm border px-3 py-2 text-left transition-colors duration-150',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                        selected?.key === entry.key
                          ? 'border-primary/60 bg-primary/10'
                          : 'border-border hover:border-primary/40',
                      )}
                    >
                      <span className="block font-mono text-xs text-foreground">{entry.title}</span>
                      <span className="block font-mono text-[11px] text-muted-foreground">
                        {entry.summary}
                      </span>
                    </button>
                  ))}
                </div>
              ),
            )}
          </div>

          <div className="space-y-2">
            <pre
              data-testid="preset-body"
              className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-sm border border-border bg-background/60 p-3 font-mono text-xs text-foreground/90"
            >
              {selected?.body}
            </pre>
            {selectedTools !== null && (
              <p data-testid="preset-tools" className="font-mono text-[11px] text-muted-foreground">
                Настроит инструменты: {selectedTools.length} из {TOOL_INFO.length}
              </p>
            )}
          </div>
        </div>
      )}

      <div className="mt-6 flex items-center justify-end gap-3">
        {confirming && (
          <span role="alert" className="mr-auto font-mono text-xs text-amber-400">
            {selectedTools !== null
              ? 'Текущий характер и настройки инструментов будут заменены'
              : 'Текущий характер будет заменён'}
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
