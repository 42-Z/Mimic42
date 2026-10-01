import { describe, expect, test } from 'bun:test';
import { groupAgentToggles } from '@/lib/activity/group';
import { isStackOpen, setStackOpen } from '@/lib/activity/expand';
import { buildActivityFeed, type ActivityItem } from '@/lib/activity/normalize';
import { renderToStaticMarkup } from 'react-dom/server';
import { LifecycleStack } from '@/components/activity/LifecycleStack';
import { Button } from '@/components/ui/button';

function event(id: string, eventType = 'agent.started', failed = false): ActivityItem {
  const item = buildActivityFeed([], [{
    id,
    agent_id: 'agent-1',
    event_type: eventType,
    status: failed ? 'failed' : 'succeeded',
    created_at: '2026-10-01T12:00:00Z',
  }])[0];
  if (!item) throw new Error('Expected lifecycle event');
  return item;
}

describe('groupAgentToggles', () => {
  test('stacks alternating starts and stops without changing original items', () => {
    const items = [event('1'), event('2', 'agent.stopped'), event('3')];
    const groups = groupAgentToggles(items);
    expect(groups.map((group) => group.map((item) => item.id))).toEqual([['evt:1', 'evt:2', 'evt:3']]);
    expect(items).toHaveLength(3);
    expect(groups[0]?.[0]).toBe(items[0]);
  });

  test('does not stack across another event or a failure', () => {
    const items = [event('1'), event('2', 'context.reset'), event('3'), event('4', 'agent.started', true), event('5')];
    expect(groupAgentToggles(items).map((group) => group.length)).toEqual([1, 1, 1, 1, 1]);
  });

  test('does not combine different agents', () => {
    expect(groupAgentToggles([event('1'), { ...event('2'), agentId: 'agent-2' }])).toHaveLength(2);
  });

  test('handles empty feeds and single events', () => {
    expect(groupAgentToggles([])).toEqual([]);
    expect(groupAgentToggles([event('1')])).toHaveLength(1);
  });

  test('renders a collapsed stack with a count and the full timestamped history', () => {
    const html = renderToStaticMarkup(
      <LifecycleStack
        items={[event('1'), event('2', 'agent.stopped')]}
        isOpen={false}
        onToggle={() => {}}
      />,
    );
    expect(html).toContain('<details');
    expect(html).not.toContain(' open=');
    expect(html).toContain('×2');
    expect(html).toContain('Агент запущен');
    expect(html).toContain('Агент остановлен');
    expect(html.match(/tabular-nums/g)).toHaveLength(4);
  });

  test('an open stack survives group growth from either side', () => {
    // Стек раскрыт по событиям 2 и 3; «Загрузить ещё» дописало старое событие 1,
    // realtime добавил сверху событие 4 — идентичность группы не потерялась.
    const expanded = setStackOpen(new Set<string>(), ['evt:2', 'evt:3'], true);
    expect(isStackOpen(['evt:2', 'evt:3', 'evt:1'], expanded)).toBe(true);
    expect(isStackOpen(['evt:4', 'evt:2', 'evt:3', 'evt:1'], expanded)).toBe(true);

    // А посторонняя группа с другими id остаётся закрытой.
    expect(isStackOpen(['evt:9', 'evt:8'], expanded)).toBe(false);

    const collapsed = setStackOpen(expanded, ['evt:2', 'evt:3'], false);
    expect(isStackOpen(['evt:4', 'evt:2', 'evt:3', 'evt:1'], collapsed)).toBe(false);
  });

  test('warning buttons use the amber fill and dark foreground', () => {
    const html = renderToStaticMarkup(<Button variant="warning">Сбросить</Button>);
    expect(html).toContain('bg-warning');
    expect(html).toContain('border-warning');
    expect(html).toContain('text-primary-foreground');
    expect(html).toContain('hover:bg-warning/90');
  });
});
