import type { PromptPresetRow, PresetFavoriteRow } from '@/types';

/** Карточка каталога: витрина или «мои». */
export interface CatalogEntry {
  id: string;
  title: string;
  summary: string;
  body: string;
  settings: Record<string, unknown> | null;
  authorId: string | null;
  authorName: string | null;
  published: boolean;
  isOfficial: boolean;
}

export interface CatalogEntries {
  store: CatalogEntry[];
  mine: CatalogEntry[];
}

/**
 * Магазин — официальные активные плюс чужие выложенные; «Мои» — свои
 * черновики и выложенные. Официальные впереди, дальше по названию.
 */
export function buildCatalogEntries(
  presets: PromptPresetRow[],
  userId: string | null,
  authorNames: Map<string, string | null>,
): CatalogEntries {
  const entry = (preset: PromptPresetRow): CatalogEntry => ({
    id: preset.id,
    title: preset.title,
    summary: preset.summary,
    body: preset.body,
    settings: preset.settings,
    authorId: preset.owner_id,
    authorName: preset.owner_id
      ? preset.owner_id === userId
        ? null
        : authorNames.get(preset.owner_id) ?? null
      : null,
    published: preset.published_at !== null,
    isOfficial: preset.owner_id === null,
  });

  const store = presets
    .filter(
      (preset) =>
        preset.owner_id === null ||
        (preset.published_at !== null && preset.owner_id !== userId),
    )
    .map(entry)
    .sort((a, b) => {
      if (a.isOfficial !== b.isOfficial) return a.isOfficial ? -1 : 1;
      return a.title.localeCompare(b.title, 'ru');
    });

  const mine = presets
    .filter((preset) => preset.owner_id !== null && preset.owner_id === userId)
    .map(entry)
    .sort((a, b) => a.title.localeCompare(b.title, 'ru'));

  return { store, mine };
}

/** Карточки избранного для страницы: живые и замороженные. */
export interface FavoriteEntry {
  favoriteId: string;
  title: string;
  summary: string;
  body: string;
  frozen: boolean;
}

export function buildFavoriteEntries(
  favorites: PresetFavoriteRow[],
  presets: PromptPresetRow[],
): FavoriteEntry[] {
  const liveById = new Map(presets.map((preset) => [preset.id, preset]));
  return favorites
    .map((favorite) => {
      const source = favorite.preset_id ? liveById.get(favorite.preset_id) : undefined;
      return {
        favoriteId: favorite.id,
        title: source?.title ?? favorite.frozen_title ?? 'Без названия',
        summary: source?.summary ?? favorite.frozen_summary ?? '',
        body: source ? source.body : favorite.frozen_body ?? '',
        frozen: !source,
      };
    })
    .sort((a, b) => a.title.localeCompare(b.title, 'ru'));
}

/** Поиск по названию и описанию без учёта регистра. */
export function filterCatalog(entries: CatalogEntry[], query: string): CatalogEntry[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return entries;
  return entries.filter(
    (entry) =>
      entry.title.toLowerCase().includes(needle) ||
      entry.summary.toLowerCase().includes(needle),
  );
}
