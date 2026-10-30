'use client';

import { useEffect, useState } from 'react';
import { Bot, Network, Search, UserRound, UsersRound } from 'lucide-react';
import {
  useAdminActions,
  useAdminProxyOptions,
  useAdminUser,
  useAdminUsers,
} from '@/hooks/useAdmin';
import { AgentStatusBadge } from '@/components/agents/AgentStatusBadge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Modal } from '@/components/ui/modal';
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
import { useToast } from '@/components/ui/toast';
import type { AgentState, ApiError } from '@/types';
import type { AdminAgentProxy, AdminAgentSummary, AdminUserSummary } from '@/types/admin';

const USER_PAGE_SIZE = 25;
const AGENT_PAGE_SIZE = 5;
const MAX_SEARCH_LENGTH = 200;
const MAX_PAGE_NUMBER = 1_000_000;
const STATE_ORDER: AgentState[] = ['running', 'starting', 'stopping', 'stopped', 'draft', 'error'];

interface UserFilters {
  q: string;
  page: number;
}

function normalizeSearch(value: string): string {
  return value.trim().slice(0, MAX_SEARCH_LENGTH);
}

function parsePage(value: string | null): number {
  if (!value || !/^[1-9]\d*$/.test(value)) return 1;
  const page = Number(value);
  return Number.isSafeInteger(page) && page <= MAX_PAGE_NUMBER ? page : 1;
}

function readFiltersFromLocation(): UserFilters {
  if (typeof window === 'undefined') return { q: '', page: 1 };
  const params = new URLSearchParams(window.location.search);
  return {
    q: normalizeSearch(params.get('q') ?? ''),
    page: parsePage(params.get('page')),
  };
}

function writeFiltersToLocation(filters: UserFilters, historyMode: 'push' | 'replace'): void {
  const url = new URL(window.location.href);
  if (filters.q) url.searchParams.set('q', filters.q);
  else url.searchParams.delete('q');
  if (filters.page > 1) url.searchParams.set('page', String(filters.page));
  else url.searchParams.delete('page');

  const nextUrl = `${url.pathname}${url.search}${url.hash}`;
  if (historyMode === 'push') window.history.pushState(window.history.state, '', nextUrl);
  else window.history.replaceState(window.history.state, '', nextUrl);
}

function registrationDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(parsed);
}

function StateSummary({ states }: { states: AdminUserSummary['states'] }) {
  const entries = STATE_ORDER.flatMap((state) => {
    const count = states[state] ?? 0;
    return count > 0 ? [{ state, count }] : [];
  });

  if (entries.length === 0) {
    return <span className="text-sm text-muted-foreground">—</span>;
  }

  return (
    <div
      aria-label="Состояния мимиков"
      className="flex flex-wrap items-center gap-1.5"
      role="group"
    >
      {entries.map(({ state, count }) => (
        <span className="inline-flex items-center gap-1" key={state}>
          <AgentStatusBadge size="sm" state={state} />
          <span
            aria-label={`Количество: ${count}`}
            className="font-mono text-xs tabular-nums text-muted-foreground"
          >
            ×{count}
          </span>
        </span>
      ))}
    </div>
  );
}

function UserListSkeleton() {
  return (
    <div aria-label="Загружаем пользователей" aria-busy="true" className="space-y-3" role="status">
      <Skeleton className="h-10 w-full" />
      {[0, 1, 2, 3].map((row) => (
        <Skeleton className="h-12 w-full" key={row} />
      ))}
    </div>
  );
}

function UserRow({
  user,
  onOpen,
}: {
  user: AdminUserSummary;
  onOpen: (userId: string) => void;
}) {
  return (
    <TableRow>
      <TableCell className="min-w-40 whitespace-normal">
        <span className="flex min-w-0 items-center gap-2">
          <UserRound aria-hidden="true" className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="break-words font-medium">{user.display_name?.trim() || 'Без имени'}</span>
        </span>
      </TableCell>
      <TableCell className="max-w-56 whitespace-normal break-all text-sm text-muted-foreground">
        {user.email?.trim() || 'Не указан'}
      </TableCell>
      <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
        {registrationDate(user.created_at)}
      </TableCell>
      <TableCell>
        <Button
          aria-label={`Мимики (${user.agents_total})`}
          onClick={() => onOpen(user.user_id)}
          size="sm"
          variant="ghost"
        >
          <Bot aria-hidden="true" className="h-4 w-4" data-icon="inline-start" />
          Мимики ({user.agents_total})
        </Button>
      </TableCell>
      <TableCell className="whitespace-normal">
        <StateSummary states={user.states} />
      </TableCell>
    </TableRow>
  );
}

function proxyName(proxy: AdminAgentProxy): string {
  return proxy.label?.trim() || `${proxy.host}:${proxy.port}`;
}

function UserAgentsTable({
  agents,
  proxyOptions,
  proxyOptionsLoading,
  pendingAgentId,
  onAssignProxy,
}: {
  agents: AdminAgentSummary[];
  proxyOptions: AdminAgentProxy[];
  proxyOptionsLoading: boolean;
  pendingAgentId: string | null;
  onAssignProxy: (agentId: string, proxyId: string | null) => void;
}) {
  return (
    <Table className="min-w-[46rem] border border-border">
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Имя</TableHead>
          <TableHead scope="col">Модель</TableHead>
          <TableHead scope="col">Состояние</TableHead>
          <TableHead scope="col">Прокси</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {agents.map((agent) => {
          const options =
            agent.proxy && !proxyOptions.some((proxy) => proxy.id === agent.proxy?.id)
              ? [agent.proxy, ...proxyOptions]
              : proxyOptions;
          return (
            <TableRow key={agent.agent_id}>
              <TableCell className="max-w-64 whitespace-normal break-words font-medium">
                {agent.name}
              </TableCell>
              <TableCell className="max-w-64 whitespace-normal break-all font-mono text-xs text-muted-foreground">
                {agent.llm_model}
              </TableCell>
              <TableCell>
                <AgentStatusBadge size="sm" state={agent.state} />
              </TableCell>
              <TableCell className="min-w-52">
                <select
                  aria-label={`Прокси мимика ${agent.name}`}
                  className="h-8 w-full rounded-sm border border-border bg-background px-2 font-mono text-xs text-foreground transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-50 [&>option]:bg-card [&>option]:text-foreground"
                  disabled={proxyOptionsLoading || pendingAgentId === agent.agent_id}
                  onChange={(event) => onAssignProxy(agent.agent_id, event.target.value || null)}
                  value={agent.proxy?.id ?? ''}
                >
                  <option value="">Без прокси</option>
                  {options.map((proxy) => (
                    <option key={proxy.id} value={proxy.id}>
                      {proxyName(proxy)} · {proxy.protocol.toUpperCase()}
                      {proxy.label?.trim() ? ` · ${proxy.host}:${proxy.port}` : ''}
                      {proxy.is_active ? '' : ' · отключён'}
                    </option>
                  ))}
                </select>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export function AdminUsers() {
  const [filters, setFilters] = useState<UserFilters>(readFiltersFromLocation);
  const [searchInput, setSearchInput] = useState(filters.q);
  const [debouncedSearch, setDebouncedSearch] = useState(filters.q);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [agentPage, setAgentPage] = useState(1);
  const [pendingProxyAgentId, setPendingProxyAgentId] = useState<string | null>(null);
  const [proxyError, setProxyError] = useState<string | null>(null);
  const usersQuery = useAdminUsers(filters.q, filters.page, USER_PAGE_SIZE);
  const detailQuery = useAdminUser(selectedUserId ?? '', agentPage, AGENT_PAGE_SIZE);
  const proxyOptionsQuery = useAdminProxyOptions(selectedUserId !== null);
  const { assignAgentProxy } = useAdminActions();
  const { toast } = useToast();
  const waitingForSearch = normalizeSearch(searchInput) !== filters.q;

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(searchInput), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    const q = normalizeSearch(debouncedSearch);
    if (q === filters.q) return;

    const nextFilters = { q, page: 1 };
    setFilters(nextFilters);
    writeFiltersToLocation(nextFilters, 'replace');
  }, [debouncedSearch, filters.q]);

  useEffect(() => {
    const handlePopState = () => {
      const nextFilters = readFiltersFromLocation();
      setFilters(nextFilters);
      setSearchInput(nextFilters.q);
      setDebouncedSearch(nextFilters.q);
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  useEffect(() => {
    const total = usersQuery.data?.total;
    if (total === undefined || waitingForSearch) return;

    const lastPage = Math.max(1, Math.ceil(total / USER_PAGE_SIZE));
    if (filters.page <= lastPage) return;

    const nextFilters = { ...filters, page: lastPage };
    setFilters(nextFilters);
    writeFiltersToLocation(nextFilters, 'replace');
  }, [filters, usersQuery.data?.total, waitingForSearch]);

  useEffect(() => {
    const agents = detailQuery.data?.agents;
    if (selectedUserId === null || !agents) return;

    const lastPage = Math.max(1, Math.ceil(agents.total / agents.page_size));
    if (agentPage > lastPage) setAgentPage(lastPage);
  }, [agentPage, detailQuery.data?.agents, selectedUserId]);

  const openDetails = (userId: string) => {
    setAgentPage(1);
    setSelectedUserId(userId);
  };

  const changeUserPage = (page: number) => {
    const nextFilters = { ...filters, page };
    setFilters(nextFilters);
    writeFiltersToLocation(nextFilters, 'push');
  };

  const closeDetails = () => {
    if (pendingProxyAgentId !== null) return;
    setSelectedUserId(null);
    setAgentPage(1);
    setProxyError(null);
  };

  const assignProxy = async (agentId: string, proxyId: string | null) => {
    if (pendingProxyAgentId !== null) return;
    setPendingProxyAgentId(agentId);
    setProxyError(null);
    try {
      await assignAgentProxy(agentId, proxyId);
      toast('Прокси мимика обновлён.', 'success');
    } catch (error) {
      const detail =
        typeof error === 'object' && error !== null && 'detail' in error
          ? (error as Partial<ApiError>).detail
          : undefined;
      setProxyError(
        typeof detail === 'string' && detail
          ? detail
          : 'Не удалось сменить прокси. Повторите попытку.',
      );
    } finally {
      setPendingProxyAgentId(null);
    }
  };

  const userData = usersQuery.data;
  const detail = detailQuery.data;
  const usersPageOutOfRange =
    userData !== undefined &&
    userData.total > 0 &&
    userData.items.length === 0 &&
    filters.page > Math.max(1, Math.ceil(userData.total / USER_PAGE_SIZE));
  const detailsPageOutOfRange =
    detail !== undefined &&
    detail.agents.total > 0 &&
    detail.agents.items.length === 0 &&
    agentPage > Math.max(1, Math.ceil(detail.agents.total / detail.agents.page_size));

  return (
    <section aria-labelledby="admin-users-title" className="space-y-5">
      <header className="space-y-1">
        <h2
          className="font-display text-xl font-semibold tracking-tight text-foreground"
          id="admin-users-title"
        >
          Пользователи
        </h2>
        <p className="text-sm text-muted-foreground">Профили и состояние их мимиков.</p>
      </header>

      <FieldGroup className="max-w-xl">
        <Field>
          <FieldLabel htmlFor="admin-user-search">Поиск пользователей</FieldLabel>
          <Input
            autoComplete="off"
            id="admin-user-search"
            maxLength={MAX_SEARCH_LENGTH}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Имя или email"
            rightElement={<Search aria-hidden="true" className="h-4 w-4" />}
            type="search"
            value={searchInput}
          />
          <FieldDescription>Поиск по имени и адресу электронной почты.</FieldDescription>
        </Field>
      </FieldGroup>

      {waitingForSearch || usersQuery.isLoading || usersPageOutOfRange ? (
        <UserListSkeleton />
      ) : usersQuery.isError ? (
        <Alert variant="destructive">
          <UsersRound aria-hidden="true" />
          <div className="min-w-0">
            <AlertTitle>Не удалось загрузить пользователей</AlertTitle>
            <AlertDescription>Список временно недоступен. Повторите запрос.</AlertDescription>
            <Button
              className="mt-4"
              onClick={() => void usersQuery.refetch()}
              size="sm"
              variant="outline"
            >
              Повторить
            </Button>
          </div>
        </Alert>
      ) : userData && userData.items.length === 0 ? (
        <Empty className="min-h-48">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <UsersRound aria-hidden="true" className="h-5 w-5 text-muted-foreground" />
            </EmptyMedia>
            <EmptyTitle>{filters.q ? 'Пользователи не найдены' : 'Пользователей пока нет'}</EmptyTitle>
            <EmptyDescription>
              {filters.q
                ? 'Измените поисковый запрос и попробуйте снова.'
                : 'Зарегистрированные профили появятся здесь.'}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : userData ? (
        <>
          <Table className="min-w-[48rem] border border-border">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Пользователь</TableHead>
                <TableHead scope="col">Email</TableHead>
                <TableHead scope="col">Зарегистрирован</TableHead>
                <TableHead scope="col">Мимики</TableHead>
                <TableHead scope="col">Состояния</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {userData.items.map((user) => (
                <UserRow key={user.user_id} onOpen={openDetails} user={user} />
              ))}
            </TableBody>
          </Table>
          <AdminPagination
            onPageChange={changeUserPage}
            page={userData.page}
            pageSize={userData.page_size}
            total={userData.total}
          />
        </>
      ) : null}

      <Modal
        className="max-h-[90dvh] overflow-y-auto"
        description="Профиль пользователя и список его мимиков."
        isOpen={selectedUserId !== null}
        onClose={closeDetails}
        size="xl"
        title="Мимики пользователя"
      >
        {detailQuery.isLoading || detailsPageOutOfRange ? (
          <div aria-label="Загружаем мимиков" aria-busy="true" className="space-y-3" role="status">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        ) : detailQuery.isError ? (
          <Alert variant="destructive">
            <Bot aria-hidden="true" />
            <div className="min-w-0">
              <AlertTitle>Не удалось загрузить мимиков</AlertTitle>
              <AlertDescription>Данные пользователя временно недоступны.</AlertDescription>
              <Button
                className="mt-4"
                onClick={() => void detailQuery.refetch()}
                size="sm"
                variant="outline"
              >
                Повторить
              </Button>
            </div>
          </Alert>
        ) : detail ? (
          <div className="space-y-5">
            <dl className="grid gap-3 border-b border-border pb-4 sm:grid-cols-3">
              <div className="min-w-0">
                <dt className="font-mono text-xs text-muted-foreground">Пользователь</dt>
                <dd className="mt-1 break-words text-sm font-medium">
                  {detail.profile.display_name?.trim() || 'Без имени'}
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="font-mono text-xs text-muted-foreground">Email</dt>
                <dd className="mt-1 break-all text-sm">
                  {detail.profile.email?.trim() || 'Не указан'}
                </dd>
              </div>
              <div>
                <dt className="font-mono text-xs text-muted-foreground">Зарегистрирован</dt>
                <dd className="mt-1 text-sm">{registrationDate(detail.profile.created_at)}</dd>
              </div>
            </dl>

            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-display text-lg font-semibold">
                Мимики <span className="font-mono text-sm text-muted-foreground">({detail.profile.agents_total})</span>
              </h3>
            </div>

            {detail.agents.items.length === 0 ? (
              <Empty className="min-h-40">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <Bot aria-hidden="true" className="h-5 w-5 text-muted-foreground" />
                  </EmptyMedia>
                  <EmptyTitle>У пользователя пока нет мимиков</EmptyTitle>
                  <EmptyDescription>
                    Когда они появятся, их имя, модель и состояние будут показаны здесь.
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <>
                {proxyError && (
                  <Alert variant="destructive">
                    <Network aria-hidden="true" />
                    <div className="min-w-0">
                      <AlertTitle>Прокси не изменён</AlertTitle>
                      <AlertDescription>{proxyError}</AlertDescription>
                    </div>
                  </Alert>
                )}
                {proxyOptionsQuery.isError && (
                  <Alert>
                    <Network aria-hidden="true" />
                    <div className="min-w-0">
                      <AlertTitle>Пул прокси недоступен</AlertTitle>
                      <AlertDescription>
                        Список прокси не загрузился: сменить назначение сейчас нельзя.
                      </AlertDescription>
                    </div>
                  </Alert>
                )}
                <UserAgentsTable
                  agents={detail.agents.items}
                  onAssignProxy={(agentId, proxyId) => void assignProxy(agentId, proxyId)}
                  pendingAgentId={pendingProxyAgentId}
                  proxyOptions={proxyOptionsQuery.data ?? []}
                  proxyOptionsLoading={proxyOptionsQuery.isLoading || proxyOptionsQuery.isError}
                />
                {detail.agents.total > detail.agents.page_size || detail.agents.page > 1 ? (
                  <AdminPagination
                    onPageChange={setAgentPage}
                    page={detail.agents.page}
                    pageSize={detail.agents.page_size}
                    total={detail.agents.total}
                  />
                ) : null}
              </>
            )}
          </div>
        ) : null}
      </Modal>
    </section>
  );
}
