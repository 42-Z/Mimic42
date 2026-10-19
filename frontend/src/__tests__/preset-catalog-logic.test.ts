import { describe, expect, test } from 'bun:test';
import {
  buildCatalogEntries,
  buildFavoriteEntries,
  filterCatalog,
  minePresetStatusLabel,
} from '@/lib/presets/catalog';
import type { PromptPresetRow, PresetFavoriteRow } from '@/types';

const OFFICIAL: PromptPresetRow = {
  id: 'a',
  slug: 'rage_comments',
  title: 'Рейджбейт в комментариях',
  summary: 'спорит',
  body: 'т',
  settings: null,
  sort_order: 1,
  is_active: true,
  owner_id: null,
  published_at: null,
  created_at: '2026-09-20T00:00:00Z',
  updated_at: '2026-09-20T00:00:00Z',
};

const HIDDEN_OFFICIAL: PromptPresetRow = {
  ...OFFICIAL,
  id: 'hidden-official',
  title: 'Скрытый официальный',
  is_active: false,
};

const MINE_DRAFT: PromptPresetRow = {
  ...OFFICIAL,
  id: 'b',
  slug: 'u_b',
  title: 'Мой черновик',
  summary: 'черновик',
  owner_id: 'me',
  published_at: null,
  sort_order: 0,
};

const MINE_PUBLISHED: PromptPresetRow = {
  ...OFFICIAL,
  id: 'c',
  slug: 'u_c',
  title: 'Мой в магазине',
  summary: 'выложен',
  owner_id: 'me',
  published_at: '2026-10-11T00:00:00Z',
  sort_order: 0,
};

const MINE_HIDDEN: PromptPresetRow = {
  ...MINE_PUBLISHED,
  id: 'e',
  slug: 'u_e',
  title: 'Мой скрытый',
  is_active: false,
};

const FOREIGN_PUBLISHED: PromptPresetRow = {
  ...OFFICIAL,
  id: 'd',
  slug: 'u_d',
  title: 'Чужой выложенный',
  summary: 'магазин',
  owner_id: 'other',
  published_at: '2026-10-11T00:00:00Z',
  sort_order: 0,
};

describe('buildCatalogEntries', () => {
  test('магазин: официальные плюс чужие выложенные, без своих черновиков', () => {
    const entries = buildCatalogEntries(
      [OFFICIAL, HIDDEN_OFFICIAL, MINE_DRAFT, MINE_PUBLISHED, MINE_HIDDEN, FOREIGN_PUBLISHED],
      'me',
      new Map([['other', 'Сосед']]),
    );
    const [officialEntry, foreignEntry] = entries.store;
    if (!officialEntry || !foreignEntry) throw new Error('в магазине меньше двух пресетов');
    expect(entries.store.map((entry) => entry.id)).toEqual(['a', 'd']);
    expect(foreignEntry.authorName).toBe('Сосед');
    expect(officialEntry.isOfficial).toBe(true);
    expect(foreignEntry.isOfficial).toBe(false);
  });

  test('мои: черновики и выложенные', () => {
    const entries = buildCatalogEntries(
      [OFFICIAL, MINE_DRAFT, MINE_PUBLISHED, MINE_HIDDEN, FOREIGN_PUBLISHED],
      'me',
      new Map(),
    );
    // «Мои» держим в порядке названий: черновики рядом с выложенными.
    expect(new Set(entries.mine.map((entry) => entry.id))).toEqual(new Set(['b', 'c', 'e']));
    expect(entries.mine.find((entry) => entry.id === 'e')?.isActive).toBe(false);
  });

  test('в магазине нет невитринных чужих черновиков', () => {
    const entries = buildCatalogEntries([FOREIGN_PUBLISHED], 'me', new Map());
    expect(entries.mine).toEqual([]);
  });

  test('автор видит административное скрытие отдельно от черновика и выкладки', () => {
    const entries = buildCatalogEntries([MINE_DRAFT, MINE_PUBLISHED, MINE_HIDDEN], 'me', new Map());
    const byId = new Map(entries.mine.map((entry) => [entry.id, entry]));

    expect(minePresetStatusLabel(byId.get('b')!)).toBe('Черновик');
    expect(minePresetStatusLabel(byId.get('c')!)).toBe('В магазине');
    expect(minePresetStatusLabel(byId.get('e')!)).toBe('Скрыт администратором');
  });
});

describe('buildFavoriteEntries', () => {
  test('живое избранное подключается к пресету, замороженное — снимок', () => {
    const favorites: PresetFavoriteRow[] = [
      {
        id: 'fav-1',
        preset_id: 'd',
        frozen_title: null,
        frozen_summary: null,
        frozen_body: null,
        frozen_settings: null,
        frozen_at: null,
        created_at: '2026-10-11T00:00:00Z',
        updated_at: '2026-10-11T00:00:00Z',
      },
      {
        id: 'fav-2',
        preset_id: null,
        frozen_title: 'Замороженный',
        frozen_summary: 'копия',
        frozen_body: 'снимок',
        frozen_settings: null,
        frozen_at: '2026-10-11T01:00:00Z',
        created_at: '2026-10-11T00:00:00Z',
        updated_at: '2026-10-11T00:00:00Z',
      },
    ];
    const entries = buildFavoriteEntries(favorites, [FOREIGN_PUBLISHED]);
    expect(entries).toEqual([
      // Порядок — по названию.
      {
        favoriteId: 'fav-2',
        title: 'Замороженный',
        summary: 'копия',
        body: 'снимок',
        settings: null,
        frozen: true,
        unavailable: false,
      },
      {
        favoriteId: 'fav-1',
        title: 'Чужой выложенный',
        summary: 'магазин',
        body: 'т',
        settings: null,
        frozen: false,
        unavailable: false,
      },
    ]);
  });

  test('ссылка на скрытый пресет без загруженного снимка не поднимает старое тело', () => {
    const favorite: PresetFavoriteRow = {
      id: 'fav-stale',
      preset_id: 'hidden-foreign',
      frozen_title: null,
      frozen_summary: null,
      frozen_body: null,
      frozen_settings: null,
      frozen_at: null,
      created_at: '2026-10-11T00:00:00Z',
      updated_at: '2026-10-11T00:00:00Z',
    };

    expect(buildFavoriteEntries([favorite], [])).toMatchObject([
      {
        title: 'Пресет больше недоступен',
        summary: '',
        body: '',
        frozen: true,
        unavailable: true,
      },
    ]);
  });
});

describe('filterCatalog', () => {
  test('ищет по названию и описанию без учёта регистра', () => {
    const entries = buildCatalogEntries([OFFICIAL, FOREIGN_PUBLISHED], 'me', new Map());
    const store = entries.store;
    const [first, second] = store;
    if (!first || !second) throw new Error('в магазине меньше двух пресетов');
    expect(filterCatalog(store, 'рейдж')).toEqual([first]);
    expect(filterCatalog(store, 'МАГАЗИН')).toEqual([second]);
    expect(filterCatalog(store, '')).toEqual(store);
  });
});
