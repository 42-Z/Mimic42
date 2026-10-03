'use client';

import { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { getToolMeta, type ToolGroup } from '@/lib/activity/toolCatalog';
import { TOOL_GROUP_ORDER, TOOL_INFO, type ToolInfo } from '@/lib/tools/toolInfo';

/**
 * Переключатели инструментов агента.
 *
 * `value === null` — режим «включены все»: ключа в настройках нет.
 * Явный список — allowlist. Имена, которых нет в каталоге фронта, сохраняются
 * как есть: настройка не должна выключать инструменты из будущего бэкенда.
 */
export function ToolsSettings({
  value,
  onChange,
}: {
  value: string[] | null;
  onChange: (next: string[] | null) => void;
}) {
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState<string[]>([]);

  const knownNames = useMemo(() => TOOL_INFO.map((tool) => tool.name), []);
  const enabled = useMemo(() => (value === null ? null : new Set(value)), [value]);
  const normalizedQuery = query.trim().toLowerCase();

  const matches = (tool: ToolInfo) =>
    normalizedQuery.length === 0 ||
    tool.title.toLowerCase().includes(normalizedQuery) ||
    tool.description.toLowerCase().includes(normalizedQuery) ||
    tool.name.toLowerCase().includes(normalizedQuery);

  const isOn = (name: string) => enabled === null || enabled.has(name);

  const updateSelection = (mutate: (base: Set<string>) => void) => {
    const base = new Set(enabled ?? knownNames);
    mutate(base);
    onChange(Array.from(base));
  };

  const toggleTool = (name: string, next: boolean) =>
    updateSelection((base) => (next ? base.add(name) : base.delete(name)));

  const toggleGroup = (group: ToolGroup, next: boolean) => {
    const names = TOOL_INFO.filter((tool) => tool.group === group).map((tool) => tool.name);
    updateSelection((base) => {
      for (const name of names) {
        if (next) base.add(name);
        else base.delete(name);
      }
    });
  };

  const enabledCount =
    enabled === null ? knownNames.length : knownNames.filter((name) => enabled.has(name)).length;

  return (
    <section className="space-y-3" data-testid="tools-settings">
      <div className="space-y-1">
        <h3 className="font-display text-sm text-foreground">Инструменты</h3>
        <p className="font-mono text-xs text-muted-foreground max-w-prose">
          Что Мимик может делать в Telegram. Отключённые инструменты не показываются модели и не
          выполняются. Обычные ответы в диалогах от этого не зависят.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-xs text-muted-foreground">
          Включено {enabledCount} из {knownNames.length}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onChange(null)}
          disabled={enabled === null}
        >
          Включить все
        </Button>
      </div>

      <Input
        label="Поиск"
        placeholder="Название, описание или имя инструмента"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      <div className="space-y-2">
        {TOOL_GROUP_ORDER.map((group) => {
          const groupTools = TOOL_INFO.filter((tool) => tool.group === group.id);
          const visibleTools = groupTools.filter(matches);
          if (visibleTools.length === 0) return null;

          const isOpen = normalizedQuery.length > 0 || expanded.includes(group.id);
          const groupOnCount = groupTools.filter((tool) => isOn(tool.name)).length;

          return (
            <div key={group.id} className="rounded-sm border border-border">
              <div className="flex items-center justify-between gap-3 px-3 py-2">
                <button
                  type="button"
                  aria-expanded={isOpen}
                  data-testid={`tool-group-${group.id}`}
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
                  <span className="font-mono text-xs text-foreground">{group.title}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {groupOnCount} из {groupTools.length}
                  </span>
                </button>
                <Switch
                  checked={groupOnCount === groupTools.length}
                  onChange={(next) => toggleGroup(group.id, next)}
                  label={`Все инструменты группы «${group.title}»`}
                />
              </div>

              {isOpen && (
                <ul className="divide-y divide-border border-t border-border">
                  {visibleTools.map((tool) => {
                    const Icon = getToolMeta(tool.name).icon;
                    return (
                      <li
                        key={tool.name}
                        className="flex items-start justify-between gap-3 px-3 py-2"
                      >
                        <div className="flex min-w-0 items-start gap-2">
                          <Icon
                            className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground"
                            aria-hidden="true"
                          />
                          <div className="min-w-0">
                            <span className="block font-mono text-xs text-foreground">
                              {tool.title}
                            </span>
                            <span className="block font-mono text-[11px] text-muted-foreground">
                              {tool.description}
                            </span>
                          </div>
                        </div>
                        <Switch
                          checked={isOn(tool.name)}
                          onChange={(next) => toggleTool(tool.name, next)}
                          label={tool.title}
                        />
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
