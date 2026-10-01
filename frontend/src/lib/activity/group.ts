import type { ActivityItem } from './normalize';

export type ActivityGroup = [ActivityItem, ...ActivityItem[]];

function isAgentToggle(item: ActivityItem): boolean {
  const action = item.actions[0];
  return item.kind === 'lifecycle' && !item.failed && item.actions.length === 1 &&
    action !== undefined && action.status !== 'failed' &&
    ['agent.started', 'agent.stopped'].includes(action.eventType);
}

/** Group adjacent successful start/stop events without hiding intervening activity. */
export function groupAgentToggles(items: ActivityItem[]): ActivityGroup[] {
  const groups: ActivityGroup[] = [];
  for (const item of items) {
    const previous = groups[groups.length - 1];
    if (isAgentToggle(item) && previous && isAgentToggle(previous[0]) &&
      previous[0].agentId === item.agentId) {
      previous.push(item);
    } else {
      groups.push([item]);
    }
  }
  return groups;
}
