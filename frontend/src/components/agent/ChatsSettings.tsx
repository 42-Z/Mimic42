'use client';

import { useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  MessagesSquare,
  Radio,
  RefreshCw,
  User,
  Users,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { useAgentChats } from '@/hooks/useAgent';
import { buildChatRows, CHAT_GROUPS, toggleChats, type ChatRow } from '@/lib/chats/agentChats';
import type { AgentChatKind, ApiError } from '@/types';

const PAGE_SIZE = 100;

const GROUP_ICONS: Record<AgentChatKind, typeof Radio> = {
  channel: Radio,
  group: Users,
  private: User,
};

/**
 * Переключатели чатов и каналов агента.
 *
 * `value` — ID отключённых чатов; пусто — доступны все, включая будущие. ID, которых
 * нет в живом списке (вышел из чата, агент остановлен), сохраняются как есть.
 */
export function ChatsSettings({
  agentId,
  value,
  onChange,
}: {
  agentId: string;
  value: number[];
  onChange: (next: number[]) => void;
}) {
  const { data: chats, error, isLoading, isFetching, refetch } = useAgentChats(agentId);
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState<AgentChatKind[]>([]);
  const [shown, setShown] = useState<Record<string, number>>({});

  const disabled = useMemo(() => new Set(value), [value]);
  const rows = useMemo(() => buildChatRows(chats ?? [], disabled), [chats, disabled]);
  const knownIds = useMemo(() => new Set((chats ?? []).map((chat) => chat.id)), [chats]);
  const orphans = value.filter((id) => !knownIds.has(id));

  const normalizedQuery = query.trim().toLowerCase();
  const matches = (row: ChatRow) =>
    normalizedQuery.length === 0 ||
    row.chat.title.toLowerCase().includes(normalizedQuery) ||
    (row.chat.username ?? '').toLowerCase().includes(normalizedQuery);

  // Ошибки запроса нормализованы перехватчиком axios в ApiError.
  const apiError = error as unknown as ApiError | null;
  const notRunning = apiError?.status === 409;
  const enabledCount = rows.filter((row) => row.enabled).length;

  const setChat = (id: number, next: boolean) => onChange(toggleChats(value, [id], next));
  const setGroup = (kind: AgentChatKind, next: boolean) => {
    const ids = rows
      .filter((row) => row.chat.kind === kind && row.lockedBy === null)
      .map((row) => row.chat.id);
    onChange(toggleChats(value, ids, next));
  };

  return (
    <section className="space-y-3" data-testid="chats-settings">
      <div className="space-y-1">
        <h3 className="font-display text-sm text-foreground">Чаты и каналы</h3>
        <p className="font-mono text-xs text-muted-foreground max-w-prose">
          С какими чатами Мимик работает. Отключённый чат не получает ответов и недоступен
          инструментам. Новые чаты и каналы включаются автоматически. Если канал включён,
          его комментарии тоже доступны.
        </p>
      </div>

      {isLoading && <Skeleton style={{ height: 96 }} />}

      {notRunning && (
        <p
          data-testid="chats-not-running"
          className="font-mono text-xs text-muted-foreground max-w-prose"
        >
          Запустите агента, чтобы увидеть чаты. Уже отключённые чаты остаются в силе.
        </p>
      )}

      {apiError && !notRunning && (
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="font-mono text-xs text-crimson-400">
            {apiError.message ?? 'Не удалось получить список чатов.'}
          </p>
          <Button type="button" variant="ghost" size="sm" onClick={() => void refetch()}>
            Повторить
          </Button>
        </div>
      )}

      {chats && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-mono text-xs text-muted-foreground">
              Доступно {enabledCount} из {rows.length}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onChange([])}
              disabled={value.length === 0}
            >
              Включить все
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Обновить список"
              title="Обновить список"
              onClick={() => void refetch()}
              disabled={isFetching}
            >
              <RefreshCw
                className={isFetching ? 'h-3.5 w-3.5 animate-spin' : 'h-3.5 w-3.5'}
                aria-hidden="true"
              />
            </Button>
          </div>

          <Input
            label="Поиск чатов"
            placeholder="Название или @username"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />

          <div className="space-y-2">
            {CHAT_GROUPS.map((group) => {
              const groupRows = rows.filter((row) => row.chat.kind === group.id);
              const visibleRows = groupRows.filter(matches);
              if (visibleRows.length === 0) return null;

              const isOpen = normalizedQuery.length > 0 || expanded.includes(group.id);
              const limit = shown[group.id] ?? PAGE_SIZE;
              const onCount = groupRows.filter((row) => row.enabled).length;
              const Icon = GROUP_ICONS[group.id];

              return (
                <div key={group.id} className="rounded-sm border border-border">
                  <div className="flex items-center justify-between gap-3 px-3 py-2">
                    <button
                      type="button"
                      aria-expanded={isOpen}
                      data-testid={`chat-group-${group.id}`}
                      onClick={() =>
                        setExpanded((prev) =>
                          prev.includes(group.id)
                            ? prev.filter((id) => id !== group.id)
                            : [...prev, group.id],
                        )
                      }
                      className="flex min-w-0 flex-1 items-center gap-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                    >
                      {isOpen ? (
                        <ChevronDown
                          className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                          aria-hidden="true"
                        />
                      ) : (
                        <ChevronRight
                          className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                          aria-hidden="true"
                        />
                      )}
                      <Icon
                        className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                        aria-hidden="true"
                      />
                      <span className="font-mono text-xs text-foreground">{group.title}</span>
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {onCount} из {groupRows.length}
                      </span>
                    </button>
                    <Switch
                      checked={onCount === groupRows.length}
                      onChange={(next) => setGroup(group.id, next)}
                      label={`Все чаты группы «${group.title}»`}
                    />
                  </div>

                  {isOpen && (
                    <ul className="divide-y divide-border border-t border-border">
                      {visibleRows.slice(0, limit).map((row) => (
                        <ChatItemRow key={row.chat.id} row={row} onToggle={setChat} />
                      ))}
                      {visibleRows.length > limit && (
                        <li className="px-3 py-2">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              setShown((prev) => ({ ...prev, [group.id]: limit + PAGE_SIZE }))
                            }
                          >
                            Показать ещё
                          </Button>
                        </li>
                      )}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {orphans.length > 0 && (
        <div className="rounded-sm border border-border">
          <p className="px-3 py-2 font-mono text-xs text-muted-foreground">
            Нет в списке диалогов
          </p>
          <ul className="divide-y divide-border border-t border-border">
            {orphans.map((id) => (
              <li key={id} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="font-mono text-xs text-foreground">Чат {id}</span>
                <Switch checked={false} onChange={() => setChat(id, true)} label={`Чат ${id}`} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ChatItemRow({
  row,
  onToggle,
}: {
  row: ChatRow;
  onToggle: (id: number, next: boolean) => void;
}) {
  const { chat, enabled, lockedBy } = row;
  return (
    <li className="flex items-start justify-between gap-3 px-3 py-2">
      <div className="min-w-0">
        <span className="block font-mono text-xs text-foreground">{chat.title}</span>
        {chat.username && (
          <span className="block font-mono text-[11px] text-muted-foreground">
            @{chat.username}
          </span>
        )}
        {lockedBy && (
          <span className="mt-0.5 flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
            <MessagesSquare className="h-3 w-3 shrink-0" aria-hidden="true" />
            Комментарии канала «{lockedBy.title}»: доступна, пока канал включён
          </span>
        )}
      </div>
      <Switch
        checked={enabled}
        onChange={(next) => onToggle(chat.id, next)}
        label={chat.title}
        disabled={lockedBy !== null}
      />
    </li>
  );
}
