'use client';

import { useState } from 'react';
import { Eye, EyeOff, FileText, Pencil, Plus, Search } from 'lucide-react';
import { PresetEditorDialog } from '@/components/presets/PresetEditorDialog';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ConfirmDialog, Modal } from '@/components/ui/modal';
import { Skeleton } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { AdminPagination } from '@/components/admin/AdminPagination';
import { useAdminActions, useAdminPreset, useAdminPresets } from '@/hooks/useAdmin';
import { readEnabledTools } from '@/lib/tools/agentTools';
import { TOOL_INFO } from '@/lib/tools/toolInfo';
import type { PresetDraft } from '@/hooks/usePresetMutations';
import type { AdminPresetKind, AdminPresetSummary } from '@/types/admin';

const PAGE_SIZE = 25;
const SORT_ORDER_MIN = -2_147_483_648;
const SORT_ORDER_MAX = 2_147_483_647;

const KIND_OPTIONS: { value: AdminPresetKind; label: string }[] = [
  { value: 'all', label: 'Все' },
  { value: 'official', label: 'Официальные' },
  { value: 'published', label: 'Пользовательские' },
];

type DetailSelection = { id: string; mode: 'edit' | 'view' } | null;

function parseSortOrder(value: string): number | null {
  if (!/^-?\d+$/.test(value)) return null;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < SORT_ORDER_MIN || parsed > SORT_ORDER_MAX) {
    return null;
  }
  return parsed;
}

function PresetListSkeleton() {
  return (
    <div aria-label="Загружаем пресеты" aria-busy="true" className="space-y-3" role="status">
      <Skeleton className="h-10 w-full" />
      {[0, 1, 2, 3].map((row) => (
        <Skeleton className="h-16 w-full" key={row} />
      ))}
    </div>
  );
}

function PresetKindLabel({ preset }: { preset: AdminPresetSummary }) {
  if (preset.owner_id === null) {
    return <Badge variant="secondary">Официальный</Badge>;
  }
  return (
    <span className="font-mono text-xs text-muted-foreground">
      {preset.owner_name?.trim() || 'Без имени'}
    </span>
  );
}

function PresetVisibility({ preset }: { preset: AdminPresetSummary }) {
  return (
    <span
      className={
        preset.is_active
          ? 'font-mono text-xs text-success'
          : 'font-mono text-xs text-warning'
      }
    >
      {preset.is_active ? 'Виден' : 'Скрыт'}
    </span>
  );
}

function SortOrderControl({
  preset,
  busy,
  onSave,
}: {
  preset: AdminPresetSummary;
  busy: boolean;
  onSave: (sortOrder: number) => void;
}) {
  const [value, setValue] = useState(String(preset.sort_order));
  const parsed = parseSortOrder(value);

  return (
    <div className="flex min-w-36 items-center gap-2">
      <Input
        aria-label={`Порядок: ${preset.title}`}
        className="h-8 min-w-0 px-2 text-right tabular-nums"
        disabled={busy}
        max={SORT_ORDER_MAX}
        min={SORT_ORDER_MIN}
        onChange={(event) => setValue(event.target.value)}
        step="1"
        type="number"
        value={value}
      />
      <Button
        aria-label={`Сохранить порядок: ${preset.title}`}
        disabled={busy || parsed === null || parsed === preset.sort_order}
        onClick={() => parsed !== null && onSave(parsed)}
        size="sm"
        variant="outline"
      >
        Сохранить
      </Button>
    </div>
  );
}

export function AdminPresets() {
  const [q, setQ] = useState('');
  const [kind, setKind] = useState<AdminPresetKind>('all');
  const [page, setPage] = useState(1);
  const [selection, setSelection] = useState<DetailSelection>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [visibilityTarget, setVisibilityTarget] = useState<AdminPresetSummary | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const listQuery = useAdminPresets(q, kind, page, PAGE_SIZE);
  const selectedId = selection?.id ?? '';
  const detailQuery = useAdminPreset(selectedId);
  const actions = useAdminActions();
  const detail = detailQuery.data;
  const editorDetail =
    selection?.mode === 'edit' && detail?.owner_id === null ? detail : null;

  const closeSelection = () => setSelection(null);

  const saveOfficial = async (draft: PresetDraft) => {
    if (editorDetail) {
      await actions.updatePreset(editorDetail.id, draft);
    } else {
      await actions.createPreset(draft);
    }
    setSelection(null);
    setCreateOpen(false);
  };

  const changeVisibility = async (preset: AdminPresetSummary, isActive: boolean) => {
    if (pendingId !== null) return;
    setPendingId(preset.id);
    setActionError(null);
    try {
      await actions.setPresetVisibility(preset.id, isActive);
      setVisibilityTarget(null);
    } catch {
      setActionError('Не удалось изменить видимость пресета. Повторите попытку.');
      if (!isActive) setVisibilityTarget(null);
    } finally {
      setPendingId(null);
    }
  };

  const saveSortOrder = async (presetId: string, sortOrder: number) => {
    if (pendingId !== null) return;
    setPendingId(presetId);
    setActionError(null);
    try {
      await actions.updatePreset(presetId, { sort_order: sortOrder });
    } catch {
      setActionError('Не удалось изменить порядок пресета. Повторите попытку.');
    } finally {
      setPendingId(null);
    }
  };

  const confirmHide = () => {
    const preset = visibilityTarget;
    if (preset) void changeVisibility(preset, false);
  };

  const list = listQuery.data;

  return (
    <section aria-labelledby="admin-presets-title" className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h2
            className="font-display text-xl font-semibold tracking-tight text-foreground"
            id="admin-presets-title"
          >
            Пресеты
          </h2>
          <p className="text-sm text-muted-foreground">Официальные пресеты и опубликованные авторами.</p>
        </div>
        <Button onClick={() => setCreateOpen(true)} size="sm">
          <Plus aria-hidden="true" className="h-4 w-4" />
          Новый официальный пресет
        </Button>
      </header>

      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <FieldGroup className="max-w-xl flex-1">
          <Field>
            <FieldLabel htmlFor="admin-preset-search">Поиск пресетов</FieldLabel>
            <Input
              autoComplete="off"
              id="admin-preset-search"
              maxLength={200}
              onChange={(event) => {
                setQ(event.target.value.slice(0, 200));
                setPage(1);
              }}
              placeholder="Название или описание"
              rightElement={<Search aria-hidden="true" className="h-4 w-4" />}
              type="search"
              value={q}
            />
          </Field>
        </FieldGroup>
        <div aria-label="Тип пресета" className="flex flex-wrap gap-2" role="group">
          {KIND_OPTIONS.map((option) => (
            <Button
              aria-pressed={kind === option.value}
              key={option.value}
              onClick={() => {
                setKind(option.value);
                setPage(1);
              }}
              size="sm"
              variant={kind === option.value ? 'outline' : 'ghost'}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>

      {actionError && (
        <Alert variant="destructive">
          <AlertTitle>Действие не выполнено</AlertTitle>
          <AlertDescription>{actionError}</AlertDescription>
        </Alert>
      )}

      {listQuery.isLoading ? (
        <PresetListSkeleton />
      ) : listQuery.isError ? (
        <Alert variant="destructive">
          <FileText aria-hidden="true" />
          <div className="min-w-0">
            <AlertTitle>Не удалось загрузить пресеты</AlertTitle>
            <AlertDescription>Список временно недоступен. Повторите запрос.</AlertDescription>
            <Button className="mt-4" onClick={() => void listQuery.refetch()} size="sm" variant="outline">
              Повторить
            </Button>
          </div>
        </Alert>
      ) : list && list.items.length === 0 ? (
        <Empty className="min-h-48">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FileText aria-hidden="true" className="h-5 w-5 text-muted-foreground" />
            </EmptyMedia>
            <EmptyTitle>{q ? 'Пресеты не найдены' : 'Пресетов пока нет'}</EmptyTitle>
            <EmptyDescription>
              {q ? 'Измените поисковый запрос и попробуйте снова.' : 'Создайте первый официальный пресет.'}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : list ? (
        <>
          <Table className="min-w-[64rem] border border-border">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Пресет</TableHead>
                <TableHead scope="col">Автор</TableHead>
                <TableHead scope="col">Видимость</TableHead>
                <TableHead scope="col">Порядок</TableHead>
                <TableHead scope="col">Изменён</TableHead>
                <TableHead scope="col"><span className="sr-only">Действия</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.items.map((preset) => {
                const isOfficial = preset.owner_id === null;
                const rowBusy = pendingId === preset.id;
                return (
                  <TableRow key={preset.id}>
                    <TableCell className="min-w-64 whitespace-normal">
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="break-words font-medium">{preset.title}</span>
                          <PresetKindLabel preset={preset} />
                        </div>
                        <p className="break-words text-xs text-muted-foreground">{preset.summary}</p>
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-normal break-words">
                      {isOfficial ? 'Платформа' : preset.owner_name?.trim() || 'Без имени'}
                    </TableCell>
                    <TableCell>
                      <PresetVisibility preset={preset} />
                    </TableCell>
                    <TableCell>
                      {isOfficial ? (
                        <SortOrderControl
                          busy={pendingId !== null}
                          onSave={(sortOrder) => void saveSortOrder(preset.id, sortOrder)}
                          preset={preset}
                        />
                      ) : (
                        <span className="font-mono text-sm tabular-nums text-muted-foreground">
                          {preset.sort_order}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                      {new Intl.DateTimeFormat('ru-RU', {
                        day: 'numeric',
                        month: 'short',
                        year: 'numeric',
                      }).format(new Date(preset.updated_at))}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        {isOfficial ? (
                          <Button
                            aria-label={`Редактировать: ${preset.title}`}
                            disabled={pendingId !== null}
                            onClick={() => setSelection({ id: preset.id, mode: 'edit' })}
                            size="sm"
                            variant="ghost"
                          >
                            <Pencil aria-hidden="true" className="h-4 w-4" />
                            Редактировать
                          </Button>
                        ) : (
                          <Button
                            aria-label={`Просмотреть: ${preset.title}`}
                            disabled={pendingId !== null}
                            onClick={() => setSelection({ id: preset.id, mode: 'view' })}
                            size="icon-sm"
                            variant="ghost"
                          >
                            <FileText aria-hidden="true" className="h-4 w-4" />
                          </Button>
                        )}
                        <Button
                          aria-label={`${preset.is_active ? 'Скрыть пресет' : 'Вернуть в каталог'}: ${preset.title}`}
                          disabled={pendingId !== null}
                          onClick={() =>
                            preset.is_active
                              ? setVisibilityTarget(preset)
                              : void changeVisibility(preset, true)
                          }
                          size="icon-sm"
                          variant="ghost"
                        >
                          {preset.is_active ? (
                            <EyeOff aria-hidden="true" className="h-4 w-4" />
                          ) : (
                            <Eye aria-hidden="true" className="h-4 w-4" />
                          )}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {list.total > list.page_size || list.page > 1 ? (
            <AdminPagination
              onPageChange={setPage}
              page={list.page}
              pageSize={list.page_size}
              total={list.total}
            />
          ) : null}
        </>
      ) : null}

      <Modal
        className="max-h-[85vh] overflow-y-auto"
        description={detail?.owner_id === null ? 'Официальный пресет' : 'Опубликованный пресет автора'}
        isOpen={
          selection !== null &&
          (selection.mode === 'view' ||
            (selection.mode === 'edit' && detail !== undefined && detail.owner_id !== null))
        }
        onClose={closeSelection}
        size="xl"
        title="Просмотр пресета"
      >
        {detailQuery.isLoading ? (
          <div aria-label="Загружаем пресет" aria-busy="true" className="space-y-3" role="status">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-28 w-full" />
          </div>
        ) : detailQuery.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Не удалось загрузить пресет</AlertTitle>
            <AlertDescription>Подробности временно недоступны. Повторите запрос.</AlertDescription>
            <Button className="mt-4" onClick={() => void detailQuery.refetch()} size="sm" variant="outline">
              Повторить
            </Button>
          </Alert>
        ) : detail ? (
          <ReadOnlyPreset preset={detail} />
        ) : null}
      </Modal>

      <Modal
        className="max-h-[85vh] overflow-y-auto"
        isOpen={selection?.mode === 'edit' && !detail}
        onClose={closeSelection}
        size="lg"
        title="Загрузка официального пресета"
      >
        {detailQuery.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Не удалось загрузить пресет</AlertTitle>
            <AlertDescription>Подробности временно недоступны. Повторите запрос.</AlertDescription>
            <Button className="mt-4" onClick={() => void detailQuery.refetch()} size="sm" variant="outline">
              Повторить
            </Button>
          </Alert>
        ) : (
          <div aria-label="Загружаем официальный пресет" aria-busy="true" role="status">
            <Skeleton className="h-40 w-full" />
          </div>
        )}
      </Modal>

      <PresetEditorDialog
        initial={editorDetail}
        isOpen={createOpen || editorDetail !== null}
        onClose={() => {
          setCreateOpen(false);
          setSelection(null);
        }}
        onSave={saveOfficial}
      />

      <ConfirmDialog
        cancelLabel="Отмена"
        confirmLabel="Скрыть пресет"
        description={
          visibilityTarget?.owner_id === null
            ? 'Пресет исчезнет из каталога пользователей.'
            : 'Существующие избранные сохранятся как снимок. Новые добавления станут недоступны, а повторная публикация не разморозит старые избранные.'
        }
        isLoading={visibilityTarget !== null && pendingId === visibilityTarget.id}
        isOpen={visibilityTarget !== null}
        onClose={() => {
          if (pendingId === null) setVisibilityTarget(null);
        }}
        onConfirm={confirmHide}
        title={visibilityTarget?.owner_id === null ? 'Скрыть официальный пресет?' : 'Скрыть пользовательский пресет?'}
        variant="danger"
      />
    </section>
  );
}

function ReadOnlyPreset({ preset }: { preset: NonNullable<ReturnType<typeof useAdminPreset>['data']> }) {
  const enabledTools = readEnabledTools(preset.settings);
  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h2 className="font-display text-lg font-semibold">{preset.title}</h2>
        <p className="text-sm text-muted-foreground">{preset.summary}</p>
      </header>
      {enabledTools !== null && (
        <p className="font-mono text-xs text-muted-foreground">
          Настроит инструменты: {enabledTools.length} из {TOOL_INFO.length}
        </p>
      )}
      <pre className="max-h-[55vh] overflow-y-auto whitespace-pre-wrap break-words rounded-sm border border-border bg-background p-4 font-mono text-xs text-foreground">
        {preset.body}
      </pre>
    </div>
  );
}
