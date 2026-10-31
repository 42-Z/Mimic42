'use client';

import { useEffect, useState } from 'react';
import { Network, Pencil, Plus, Radar, Trash2, Upload } from 'lucide-react';
import { useAdminActions, useAdminProxies } from '@/hooks/useAdmin';
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
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input, Textarea } from '@/components/ui/input';
import { ConfirmDialog, Modal } from '@/components/ui/modal';
import { Skeleton } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { AdminPagination } from '@/components/admin/AdminPagination';
import { useToast } from '@/components/ui/toast';
import type { ApiError } from '@/types';
import type {
  AdminProxyImportResult,
  AdminProxyInput,
  AdminProxyProtocol,
  AdminProxySummary,
  UpdateAdminProxy,
} from '@/types/admin';

const PAGE_SIZE = 25;
const PORT_MIN = 1;
const PORT_MAX = 65_535;

interface FormState {
  label: string;
  protocol: AdminProxyProtocol;
  host: string;
  port: string;
  username: string;
  password: string;
  isActive: boolean;
}

const EMPTY_FORM: FormState = {
  label: '',
  protocol: 'socks5',
  host: '',
  port: '',
  username: '',
  password: '',
  isActive: true,
};

function apiErrorText(error: unknown, fallback: string): string {
  if (typeof error !== 'object' || error === null) return fallback;
  const detail = (error as Partial<ApiError>).detail;
  if (typeof detail === 'string' && detail && detail !== 'Проверьте поля запроса') return detail;
  const message = (error as Partial<ApiError>).message;
  return typeof message === 'string' && message ? message : fallback;
}

function parsePort(value: string): number | null {
  if (!/^\d+$/.test(value.trim())) return null;
  const port = Number(value);
  return Number.isSafeInteger(port) && port >= PORT_MIN && port <= PORT_MAX ? port : null;
}

function protocolLabel(protocol: AdminProxyProtocol): string {
  return protocol === 'socks5' ? 'SOCKS5' : 'HTTP';
}

function updatedDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(parsed);
}

function proxyName(proxy: { label: string | null; host: string; port: number }): string {
  return proxy.label?.trim() || `${proxy.host}:${proxy.port}`;
}

function validateForm(form: FormState, editing: AdminProxySummary | null): string | null {
  if (!form.host.trim()) return 'Укажите адрес прокси.';
  if (/[\s/]/.test(form.host.trim()) || form.host.includes('://')) {
    return 'Укажите только хост без схемы, слешей и пробелов.';
  }
  if (parsePort(form.port) === null) {
    return `Укажите порт от ${PORT_MIN} до ${PORT_MAX}.`;
  }
  const username = form.username.trim();
  const hasPassword = Boolean(editing?.has_password || form.password);
  if (hasPassword && !username) {
    return 'Для пароля укажите логин прокси.';
  }
  return null;
}

function ProxyListSkeleton() {
  return (
    <div aria-label="Загружаем прокси" aria-busy="true" className="flex flex-col gap-3" role="status">
      <Skeleton className="h-10 w-full" />
      {[0, 1, 2].map((row) => (
        <Skeleton className="h-14 w-full" key={row} />
      ))}
    </div>
  );
}

export function AdminProxies() {
  const [page, setPage] = useState(1);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<AdminProxySummary | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminProxySummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [checkingId, setCheckingId] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState('');
  const [importProtocol, setImportProtocol] = useState<AdminProxyProtocol>('socks5');
  const [importActive, setImportActive] = useState(true);
  const [importFileName, setImportFileName] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<AdminProxyImportResult | null>(null);

  const listQuery = useAdminProxies(page, PAGE_SIZE);
  const actions = useAdminActions();
  const { toast } = useToast();

  useEffect(() => {
    const total = listQuery.data?.total;
    if (total === undefined) return;
    const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (page > lastPage) setPage(lastPage);
  }, [listQuery.data?.total, page]);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setActionError(null);
    setEditorOpen(true);
  };

  const openImport = () => {
    setImportText('');
    setImportFileName(null);
    setImportProtocol('socks5');
    setImportActive(true);
    setImportError(null);
    setImportResult(null);
    setImportOpen(true);
  };

  const readImportFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > 200_000) {
      setImportError('Файл больше 200 КБ.');
      return;
    }
    try {
      setImportText(await file.text());
      setImportFileName(file.name);
      setImportError(null);
    } catch {
      setImportError('Не удалось прочитать файл.');
    }
  };

  const submitImport = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (importing) return;
    if (!importText.trim()) {
      setImportError('Выберите файл или вставьте содержимое.');
      return;
    }
    setImporting(true);
    setImportError(null);
    try {
      const result = await actions.importProxies({
        text: importText,
        protocol: importProtocol,
        is_active: importActive,
      });
      setImportResult(result);
      setImportOpen(false);
      toast(
        `Импорт завершён: добавлено ${result.imported}, пропущено ${result.skipped}.`,
        result.imported > 0 ? 'success' : 'warning',
      );
    } catch (error) {
      setImportError(
        apiErrorText(error, 'Не удалось импортировать прокси. Проверьте файл.'),
      );
    } finally {
      setImporting(false);
    }
  };

  const openEdit = (proxy: AdminProxySummary) => {
    setEditing(proxy);
    setForm({
      label: proxy.label ?? '',
      protocol: proxy.protocol,
      host: proxy.host,
      port: String(proxy.port),
      username: proxy.username ?? '',
      password: '',
      isActive: proxy.is_active,
    });
    setFormError(null);
    setActionError(null);
    setEditorOpen(true);
  };

  const closeEditor = () => {
    if (saving) return;
    setEditorOpen(false);
    setEditing(null);
    setFormError(null);
  };

  const setField = <Key extends keyof FormState>(key: Key, value: FormState[Key]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setFormError(null);
  };

  const submitForm = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    const validationError = validateForm(form, editing);
    if (validationError) {
      setFormError(validationError);
      return;
    }
    const port = parsePort(form.port);
    if (port === null) return;
    const username = form.username.trim();
    const password = form.password;
    setSaving(true);
    setFormError(null);
    try {
      if (editing) {
        const patch: UpdateAdminProxy = {
          label: form.label.trim() || null,
          protocol: form.protocol,
          host: form.host.trim(),
          port,
          username: username || null,
          is_active: form.isActive,
        };
        if (password) patch.password = password;
        await actions.updateProxy(editing.id, patch);
        toast('Прокси сохранён.', 'success');
      } else {
        const values: AdminProxyInput = {
          label: form.label.trim() || null,
          protocol: form.protocol,
          host: form.host.trim(),
          port,
          username: username || null,
          is_active: form.isActive,
        };
        if (password) values.password = password;
        await actions.createProxy(values);
        toast('Прокси добавлен в пул.', 'success');
      }
      setEditorOpen(false);
      setEditing(null);
    } catch (error) {
      setFormError(
        apiErrorText(
          error,
          'Не удалось сохранить прокси. Проверьте данные и повторите попытку.',
        ),
      );
    } finally {
      setSaving(false);
    }
  };

  const checkProxy = async (proxy: AdminProxySummary) => {
    if (checkingId !== null) return;
    setCheckingId(proxy.id);
    try {
      const result = await actions.checkProxy(proxy.id);
      if (result.ok) {
        toast(
          result.latency_ms === null
            ? 'Прокси отвечает.'
            : `Прокси отвечает за ${result.latency_ms} мс.`,
          'success',
        );
      } else {
        toast(result.error ?? 'Прокси не ответил.', 'error');
      }
    } catch {
      toast('Не удалось проверить прокси. Повторите попытку.', 'error');
    } finally {
      setCheckingId(null);
    }
  };

  const confirmDelete = async () => {
    const proxy = deleteTarget;
    if (!proxy || deleting) return;
    setDeleting(true);
    setActionError(null);
    try {
      await actions.deleteProxy(proxy.id);
      setDeleteTarget(null);
      toast('Прокси удалён.', 'success');
    } catch {
      setDeleteTarget(null);
      setActionError('Не удалось удалить прокси. Повторите попытку.');
    } finally {
      setDeleting(false);
    }
  };

  const list = listQuery.data;
  const pageOutOfRange =
    list !== undefined &&
    list.total > 0 &&
    list.items.length === 0 &&
    page > Math.max(1, Math.ceil(list.total / list.page_size));

  return (
    <section aria-labelledby="admin-proxies-title" className="flex flex-col gap-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2
            className="font-display text-xl font-semibold tracking-tight text-foreground"
            id="admin-proxies-title"
          >
            Прокси
          </h2>
          <p className="max-w-[65ch] text-sm text-muted-foreground">
            Пул адресов для Telegram-трафика мимиков. Новые мимики получают активный прокси
            автоматически, вручную его можно заменить или снять.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={openImport} size="sm" variant="outline">
            <Upload aria-hidden="true" className="h-4 w-4" />
            Импортировать
          </Button>
          <Button onClick={openCreate} size="sm">
            <Plus aria-hidden="true" className="h-4 w-4" />
            Новый прокси
          </Button>
        </div>
      </header>

      {actionError && (
        <Alert variant="destructive">
          <Network aria-hidden="true" />
          <div className="min-w-0">
            <AlertTitle>Действие не выполнено</AlertTitle>
            <AlertDescription>{actionError}</AlertDescription>
            <Button
              className="mt-3"
              onClick={() => setActionError(null)}
              size="sm"
              variant="outline"
            >
              Закрыть
            </Button>
          </div>
        </Alert>
      )}

      {importResult && (
        <Alert variant={importResult.errors.length > 0 ? 'destructive' : 'default'}>
          <Upload aria-hidden="true" />
          <div className="min-w-0">
            <AlertTitle>Импорт прокси</AlertTitle>
            <AlertDescription>
              Добавлено: {importResult.imported}. Пропущено: {importResult.skipped}.
              {importResult.errors.length > 0 && (
                <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 font-mono text-xs">
                  {importResult.errors.slice(0, 10).map((error, index) => (
                    <li key={`${index}-${error}`}>{error}</li>
                  ))}
                </ul>
              )}
            </AlertDescription>
            <Button
              className="mt-3"
              onClick={() => setImportResult(null)}
              size="sm"
              variant="outline"
            >
              Закрыть
            </Button>
          </div>
        </Alert>
      )}

      {listQuery.isLoading || pageOutOfRange ? (
        <ProxyListSkeleton />
      ) : listQuery.isError ? (
        <Alert variant="destructive">
          <Network aria-hidden="true" />
          <div className="min-w-0">
            <AlertTitle>Не удалось загрузить прокси</AlertTitle>
            <AlertDescription>Пул временно недоступен. Повторите запрос.</AlertDescription>
            <Button
              className="mt-4"
              onClick={() => void listQuery.refetch()}
              size="sm"
              variant="outline"
            >
              Повторить
            </Button>
          </div>
        </Alert>
      ) : list && list.items.length === 0 ? (
        <Empty className="min-h-52">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Network aria-hidden="true" className="h-5 w-5 text-muted-foreground" />
            </EmptyMedia>
            <EmptyTitle>Прокси пока нет</EmptyTitle>
            <EmptyDescription>
              Пока пул пуст, мимики подключаются к Telegram напрямую. Добавьте SOCKS5 или HTTP
              прокси, чтобы новые мимики сразу получили его.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : list ? (
        <>
          <Table className="min-w-[56rem] border border-border">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Название</TableHead>
                <TableHead scope="col">Протокол</TableHead>
                <TableHead scope="col">Адрес</TableHead>
                <TableHead scope="col">Состояние</TableHead>
                <TableHead scope="col">Используют</TableHead>
                <TableHead scope="col">Обновлён</TableHead>
                <TableHead scope="col">Действия</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.items.map((proxy) => (
                <TableRow key={proxy.id}>
                  <TableCell className="max-w-56 whitespace-normal break-words font-medium">
                    {proxyName(proxy)}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{protocolLabel(proxy.protocol)}</Badge>
                  </TableCell>
                  <TableCell className="whitespace-normal break-all font-mono text-xs text-muted-foreground">
                    {proxy.host}:{proxy.port}
                  </TableCell>
                  <TableCell>
                    <Badge variant={proxy.is_active ? 'secondary' : 'outline'}>
                      {proxy.is_active ? 'Активен' : 'Отключён'}
                    </Badge>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    <span className="font-mono text-xs tabular-nums">{proxy.agents_total}</span>
                    {proxy.onboarding_total > 0 && (
                      <span className="ml-1 font-mono text-[11px] text-muted-foreground">
                        +{proxy.onboarding_total} онбординг
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                    {updatedDate(proxy.updated_at)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Button
                        aria-label={`Проверить прокси ${proxyName(proxy)}`}
                        disabled={checkingId !== null}
                        isLoading={checkingId === proxy.id}
                        onClick={() => void checkProxy(proxy)}
                        size="icon-sm"
                        title="Проверить"
                        variant="ghost"
                      >
                        <Radar aria-hidden="true" className="h-4 w-4" />
                      </Button>
                      <Button
                        aria-label={`Изменить прокси ${proxyName(proxy)}`}
                        onClick={() => openEdit(proxy)}
                        size="icon-sm"
                        title="Изменить"
                        variant="ghost"
                      >
                        <Pencil aria-hidden="true" className="h-4 w-4" />
                      </Button>
                      <Button
                        aria-label={`Удалить прокси ${proxyName(proxy)}`}
                        onClick={() => setDeleteTarget(proxy)}
                        size="icon-sm"
                        title="Удалить"
                        variant="ghost"
                      >
                        <Trash2 aria-hidden="true" className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <AdminPagination
            onPageChange={setPage}
            page={list.page}
            pageSize={list.page_size}
            total={list.total}
          />
        </>
      ) : null}

      <Modal
        className="max-h-[90dvh] overflow-y-auto"
        description={
          editing
            ? 'Пароль хранится зашифрованным и не показывается. Пустое поле оставляет прежний.'
            : 'Адрес получит новый мимик, если прокси активен.'
        }
        isOpen={editorOpen}
        onClose={closeEditor}
        size="lg"
        title={editing ? 'Изменить прокси' : 'Новый прокси'}
      >
        <form className="flex flex-col gap-5" onSubmit={(event) => void submitForm(event)}>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="proxy-label">Название</FieldLabel>
              <Input
                autoComplete="off"
                disabled={saving}
                id="proxy-label"
                maxLength={100}
                onChange={(event) => setField('label', event.target.value)}
                placeholder="Необязательно"
                value={form.label}
              />
              <FieldDescription>
                Если не заполнить, в списке будет показан адрес прокси.
              </FieldDescription>
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel id="proxy-protocol-label">Протокол</FieldLabel>
                <ToggleGroup
                  aria-labelledby="proxy-protocol-label"
                  disabled={saving}
                  onValueChange={(value) => {
                    if (value === 'socks5' || value === 'http') setField('protocol', value);
                  }}
                  type="single"
                  value={form.protocol}
                  variant="outline"
                >
                  <ToggleGroupItem value="socks5">SOCKS5</ToggleGroupItem>
                  <ToggleGroupItem value="http">HTTP</ToggleGroupItem>
                </ToggleGroup>
              </Field>

              <Field>
                <FieldLabel htmlFor="proxy-port">Порт</FieldLabel>
                <Input
                  disabled={saving}
                  id="proxy-port"
                  inputMode="numeric"
                  maxLength={5}
                  onChange={(event) => setField('port', event.target.value)}
                  placeholder="1080"
                  required
                  value={form.port}
                />
              </Field>
            </div>

            <Field>
              <FieldLabel htmlFor="proxy-host">Адрес</FieldLabel>
              <Input
                autoComplete="off"
                disabled={saving}
                id="proxy-host"
                maxLength={255}
                onChange={(event) => setField('host', event.target.value)}
                placeholder="proxy.example.com"
                required
                value={form.host}
              />
              <FieldDescription>Только хост, без схемы и слешей.</FieldDescription>
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="proxy-username">Логин</FieldLabel>
                <Input
                  autoComplete="off"
                  disabled={saving}
                  id="proxy-username"
                  maxLength={255}
                  onChange={(event) => setField('username', event.target.value)}
                  value={form.username}
                />
              </Field>

              <Field>
                <FieldLabel htmlFor="proxy-password">Пароль</FieldLabel>
                <Input
                  autoComplete="new-password"
                  disabled={saving}
                  id="proxy-password"
                  maxLength={512}
                  onChange={(event) => setField('password', event.target.value)}
                  placeholder={editing?.has_password ? 'Оставить прежний' : 'Необязательно'}
                  type="password"
                  value={form.password}
                />
              </Field>
            </div>

            <Field orientation="horizontal">
              <Switch
                checked={form.isActive}
                disabled={saving}
                label="Прокси активен"
                onChange={(checked) => setField('isActive', checked)}
              />
              <div className="flex flex-col gap-0.5">
                <FieldLabel>Активен</FieldLabel>
                <FieldDescription>
                  Активные прокси получают новые мимики при онбординге.
                </FieldDescription>
              </div>
            </Field>
          </FieldGroup>

          {editing && editing.agents_total + editing.onboarding_total > 0 && (
            <p className="text-xs leading-relaxed text-muted-foreground">
              Новые адрес или пароль применятся к работающим мимикам после их перезапуска.
            </p>
          )}

          {formError && (
            <Alert variant="destructive">
              <AlertTitle>Прокси не сохранён</AlertTitle>
              <AlertDescription>{formError}</AlertDescription>
            </Alert>
          )}

          <div className="flex flex-wrap justify-end gap-2">
            <Button disabled={saving} onClick={closeEditor} type="button" variant="ghost">
              Отмена
            </Button>
            <Button isLoading={saving} type="submit">
              {editing ? 'Сохранить' : 'Добавить'}
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        className="max-h-[90dvh] overflow-y-auto"
        description="Файл .txt: host:port:login:password, host:port или socks5://login:password@host:port."
        isOpen={importOpen}
        onClose={() => {
          if (!importing) setImportOpen(false);
        }}
        size="lg"
        title="Импорт прокси"
      >
        <form className="flex flex-col gap-5" onSubmit={(event) => void submitImport(event)}>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="proxy-import-file">Файл</FieldLabel>
              <Input
                accept=".txt,text/plain"
                disabled={importing}
                id="proxy-import-file"
                key={importOpen ? 'import-open' : 'import-closed'}
                onChange={(event) => void readImportFile(event.target.files?.[0])}
                type="file"
              />
              <FieldDescription>
                {importFileName
                  ? `Выбран файл: ${importFileName}`
                  : 'Можно выбрать файл или вставить строки ниже.'}
              </FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="proxy-import-text">Содержимое</FieldLabel>
              <Textarea
                disabled={importing}
                id="proxy-import-text"
                maxLength={200_000}
                onChange={(event) => {
                  setImportText(event.target.value);
                  setImportError(null);
                }}
                placeholder={'1.2.3.4:1080:login:password\n5.6.7.8:3128'}
                rows={7}
                value={importText}
              />
              <FieldDescription>
                По одному прокси на строку. Пустые строки и строки с # пропускаются.
              </FieldDescription>
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel id="proxy-import-protocol-label">Протокол</FieldLabel>
                <ToggleGroup
                  aria-labelledby="proxy-import-protocol-label"
                  disabled={importing}
                  onValueChange={(value) => {
                    if (value === 'socks5' || value === 'http') setImportProtocol(value);
                  }}
                  type="single"
                  value={importProtocol}
                  variant="outline"
                >
                  <ToggleGroupItem value="socks5">SOCKS5</ToggleGroupItem>
                  <ToggleGroupItem value="http">HTTP</ToggleGroupItem>
                </ToggleGroup>
              </Field>

              <Field orientation="horizontal">
                <Switch
                  checked={importActive}
                  disabled={importing}
                  label="Импортируемые прокси активны"
                  onChange={setImportActive}
                />
                <div className="flex flex-col gap-0.5">
                  <FieldLabel>Активны</FieldLabel>
                  <FieldDescription>Новые мимики смогут их получить.</FieldDescription>
                </div>
              </Field>
            </div>
          </FieldGroup>

          {importError && (
            <Alert variant="destructive">
              <AlertTitle>Импорт не выполнен</AlertTitle>
              <AlertDescription>{importError}</AlertDescription>
            </Alert>
          )}

          <div className="flex flex-wrap justify-end gap-2">
            <Button
              disabled={importing}
              onClick={() => setImportOpen(false)}
              type="button"
              variant="ghost"
            >
              Отмена
            </Button>
            <Button isLoading={importing} type="submit">
              Импортировать
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        confirmLabel="Удалить"
        description="Мимики перейдут на другой активный прокси, а если его нет — на прямое соединение."
        isLoading={deleting}
        isOpen={deleteTarget !== null}
        onClose={() => {
          if (!deleting) setDeleteTarget(null);
        }}
        onConfirm={() => void confirmDelete()}
        title={`Удалить «${deleteTarget ? proxyName(deleteTarget) : ''}»?`}
        variant="danger"
      />
    </section>
  );
}
