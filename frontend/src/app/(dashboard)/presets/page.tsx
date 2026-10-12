'use client';

import { useEffect, useMemo, useState } from 'react';
import { Library, Plus, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/card';
import { PresetEditorDialog } from '@/components/presets/PresetEditorDialog';
import { getSupabaseClient } from '@/lib/supabase/client';
import { readEnabledTools } from '@/lib/tools/agentTools';
import { TOOL_INFO } from '@/lib/tools/toolInfo';
import { cn } from '@/lib/utils';
import { usePromptPresets } from '@/hooks/usePromptPresets';
import { usePresetFavorites } from '@/hooks/usePresetFavorites';
import { usePresetAuthors } from '@/hooks/usePresetAuthors';
import {
  useCreatePreset,
  useDeletePreset,
  useFavoritePreset,
  usePublishPreset,
  useUnfavoriteByPreset,
  useUnfavoritePreset,
  useUnpublishPreset,
  useUpdatePreset,
  type PresetDraft,
} from '@/hooks/usePresetMutations';
import {
  buildCatalogEntries,
  buildFavoriteEntries,
  filterCatalog,
  type CatalogEntry,
  type FavoriteEntry,
} from '@/lib/presets/catalog';

type TabKey = 'store' | 'mine' | 'favorites';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'store', label: 'Магазин' },
  { key: 'mine', label: 'Мои' },
  { key: 'favorites', label: 'Избранное' },
];

export default function PresetsPage() {
  const { data: presets, isLoading, isError } = usePromptPresets();
  const { data: favorites } = usePresetFavorites();
  const { data: authors } = usePresetAuthors();

  const [tab, setTab] = useState<TabKey>('store');
  const [search, setSearch] = useState('');
  const [userId, setUserId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<CatalogEntry | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

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

  const create = useCreatePreset();
  const update = useUpdatePreset();
  const publish = usePublishPreset();
  const unpublish = useUnpublishPreset();
  const remove = useDeletePreset();
  const favorite = useFavoritePreset();
  const unfavoriteByPreset = useUnfavoriteByPreset();
  const unfavorite = useUnfavoritePreset();

  const authorNames = useMemo(
    () => new Map((authors ?? []).map((author) => [author.id, author.display_name])),
    [authors],
  );

  const entries = useMemo(
    () => buildCatalogEntries(presets ?? [], userId, authorNames),
    [presets, userId, authorNames],
  );
  const favoriteEntries = useMemo(
    () => buildFavoriteEntries(favorites ?? [], presets ?? []),
    [favorites, presets],
  );

  // Карта preset_id → id избранного: убирать живое избранное можно по пресету.
  const favoriteIdByPreset = useMemo(
    () =>
      new Map(
        (favorites ?? []).filter((f) => f.preset_id).map((f) => [f.preset_id as string, f.id]),
      ),
    [favorites],
  );

  const storeVisible = filterCatalog(entries.store, search);

  const handleSave = async (draft: PresetDraft) => {
    if (editing) {
      await update.mutateAsync({ id: editing.id, draft });
    } else {
      await create.mutateAsync(draft);
    }
  };

  const openEditor = (entry: CatalogEntry | null) => {
    setEditing(entry);
    setEditorOpen(true);
  };

  const busy = create.isPending || update.isPending;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Library className="h-5 w-5 text-primary" aria-hidden="true" />
          <h1 className="text-xl font-semibold text-foreground">Пресеты</h1>
        </div>
        <Button size="sm" onClick={() => openEditor(null)} data-testid="open-preset-editor">
          <Plus className="mr-1 h-4 w-4" aria-hidden="true" />
          Создать пресет
        </Button>
      </header>

      <nav className="flex gap-1 border-b border-border" aria-label="Разделы каталога">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            data-testid={`presets-tab-${item.key}`}
            aria-current={tab === item.key}
            className={cn(
              'rounded-t-sm px-4 py-2 font-mono text-xs transition-colors duration-150',
              tab === item.key
                ? 'border-b-2 border-primary text-primary'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === 'store' && (
        <div className="space-y-4">
          <div className="relative max-w-sm">
            <Search
              className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Поиск по названию и описанию"
              data-testid="presets-store-search"
              className="pl-9"
            />
          </div>
          <StoreList
            entries={storeVisible}
            isLoading={isLoading}
            isError={isError}
            hasQuery={search.trim().length > 0}
            favoriteIdByPreset={favoriteIdByPreset}
            busy={favorite.isPending || unfavoriteByPreset.isPending}
            onFavorite={(id) => favorite.mutate(id)}
            onUnfavorite={(presetId) => unfavoriteByPreset.mutate(presetId)}
          />
        </div>
      )}

      {tab === 'mine' && (
        <MineList
          entries={entries.mine}
          isLoading={isLoading}
          isError={isError}
          confirmDeleteId={confirmDeleteId}
          busy={busy}
          onEdit={openEditor}
          onPublish={(id) => publish.mutate(id)}
          onUnpublish={(id) => unpublish.mutate(id)}
          onDelete={(id) => {
            if (confirmDeleteId === id) {
              remove.mutate(id);
              setConfirmDeleteId(null);
            } else {
              setConfirmDeleteId(id);
            }
          }}
        />
      )}

      {tab === 'favorites' && (
        <FavoritesList
          entries={favoriteEntries}
          busy={unfavorite.isPending}
          onUnfavorite={(id) => unfavorite.mutate(id)}
        />
      )}

      <PresetEditorDialog
        isOpen={editorOpen}
        onClose={() => {
          setEditorOpen(false);
          setEditing(null);
        }}
        initial={
          editing
            ? {
                id: editing.id,
                title: editing.title,
                summary: editing.summary,
                body: editing.body,
                settings: editing.settings,
              }
            : null
        }
        onSave={handleSave}
      />
    </div>
  );
}

function ToolBadge({ settings }: { settings: Record<string, unknown> | null }) {
  const enabled = readEnabledTools(settings);
  if (enabled === null) return null;
  return (
    <p className="font-mono text-[11px] text-muted-foreground">
      Настроит инструменты: {enabled.length} из {TOOL_INFO.length}
    </p>
  );
}

function StoreList({
  entries,
  isLoading,
  isError,
  hasQuery,
  favoriteIdByPreset,
  busy,
  onFavorite,
  onUnfavorite,
}: {
  entries: CatalogEntry[];
  isLoading: boolean;
  isError: boolean;
  hasQuery: boolean;
  favoriteIdByPreset: Map<string, string>;
  busy: boolean;
  onFavorite: (presetId: string) => void;
  onUnfavorite: (presetId: string) => void;
}) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }
  if (isError) {
    return (
      <p role="alert" className="font-mono text-xs text-crimson-400">
        Не удалось загрузить каталог
      </p>
    );
  }
  if (entries.length === 0) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        {hasQuery ? 'Ничего не найдено' : 'Пресетов пока нет'}
      </p>
    );
  }
  return (
    <div className="grid gap-3">
      {entries.map((entry) => {
        const favoriteId = favoriteIdByPreset.get(entry.id);
        return (
          <article
            key={entry.id}
            data-testid={`preset-card-${entry.id}`}
            className="rounded-sm border border-border p-4"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-mono text-sm text-foreground">{entry.title}</h2>
              <span className="font-mono text-[11px] text-muted-foreground">
                {entry.isOfficial ? 'Официальный' : entry.authorName ?? 'Без имени'}
              </span>
            </div>
            <p className="mt-1 font-mono text-xs text-muted-foreground">{entry.summary}</p>
            <ToolBadge settings={entry.settings} />
            {!entry.isOfficial && (
              <div className="mt-3">
                {favoriteId ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => onUnfavorite(entry.id)}
                    data-testid="preset-unfavorite"
                  >
                    В избранном
                  </Button>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => onFavorite(entry.id)}
                    data-testid="preset-favorite"
                  >
                    В избранное
                  </Button>
                )}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

function MineList({
  entries,
  isLoading,
  isError,
  confirmDeleteId,
  busy,
  onEdit,
  onPublish,
  onUnpublish,
  onDelete,
}: {
  entries: CatalogEntry[];
  isLoading: boolean;
  isError: boolean;
  confirmDeleteId: string | null;
  busy: boolean;
  onEdit: (entry: CatalogEntry) => void;
  onPublish: (id: string) => void;
  onUnpublish: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }
  if (isError) {
    return (
      <p role="alert" className="font-mono text-xs text-crimson-400">
        Не удалось загрузить свои пресеты
      </p>
    );
  }
  if (entries.length === 0) {
    return <p className="font-mono text-xs text-muted-foreground">Своих пресетов пока нет</p>;
  }
  return (
    <div className="grid gap-3">
      {entries.map((entry) => (
        <article
          key={entry.id}
          data-testid={`preset-card-${entry.id}`}
          className="rounded-sm border border-border p-4"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-mono text-sm text-foreground">{entry.title}</h2>
            <span className="font-mono text-[11px] text-muted-foreground">
              {entry.published ? 'В магазине' : 'Черновик'}
            </span>
          </div>
          <p className="mt-1 font-mono text-xs text-muted-foreground">{entry.summary}</p>
          <ToolBadge settings={entry.settings} />
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="ghost" size="sm" onClick={() => onEdit(entry)} data-testid="preset-edit">
              Редактировать
            </Button>
            {entry.published ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onUnpublish(entry.id)}
                data-testid="preset-unpublish"
              >
                Снять с витрины
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => onPublish(entry.id)}
                data-testid="preset-publish"
              >
                Выложить
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDelete(entry.id)}
              data-testid="preset-delete"
              className="text-crimson-400 hover:text-crimson-300"
            >
              {confirmDeleteId === entry.id ? 'Точно удалить?' : 'Удалить'}
            </Button>
          </div>
        </article>
      ))}
    </div>
  );
}

function FavoritesList({
  entries,
  busy,
  onUnfavorite,
}: {
  entries: FavoriteEntry[];
  busy: boolean;
  onUnfavorite: (favoriteId: string) => void;
}) {
  if (entries.length === 0) {
    return (
      <p className="font-mono text-xs text-muted-foreground">В избранном пока ничего нет</p>
    );
  }
  return (
    <div className="grid gap-3">
      {entries.map((entry) => (
        <article
          key={entry.favoriteId}
          data-testid={`preset-card-${entry.favoriteId}`}
          className="rounded-sm border border-border p-4"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-mono text-sm text-foreground">{entry.title}</h2>
            {entry.frozen && (
              <span
                data-testid="favorite-frozen"
                className="font-mono text-[11px] text-amber-400"
              >
                Копия
              </span>
            )}
          </div>
          <p className="mt-1 font-mono text-xs text-muted-foreground">{entry.summary}</p>
          <div className="mt-3">
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => onUnfavorite(entry.favoriteId)}
              data-testid="preset-unfavorite"
            >
              Убрать из избранного
            </Button>
          </div>
        </article>
      ))}
    </div>
  );
}
