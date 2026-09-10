import {
  Play,
  Square,
  AlertTriangle,
  MessageSquareX,
  Timer,
  type LucideIcon,
} from 'lucide-react';

export interface EventMeta {
  ru: string;
  icon: LucideIcon;
}

/**
 * Lifecycle and runtime events (non-tool agent_events).
 * `tool.<name>` events are handled by the tool catalog.
 */
export const EVENT_CATALOG: Record<string, EventMeta> = {
  'agent.started': { ru: 'Агент запущен', icon: Play },
  'agent.stopped': { ru: 'Агент остановлен', icon: Square },
  'agent.start_failed': { ru: 'Не удалось запустить агента', icon: AlertTriangle },
  'model.failed': { ru: 'Модель не ответила', icon: AlertTriangle },
  'turn.failed': { ru: 'Ход завершился ошибкой', icon: AlertTriangle },
  'message.send_failed': { ru: 'Не удалось отправить ответ', icon: MessageSquareX },
  'timer.fired': { ru: 'Сработал отложенный таймер', icon: Timer },
  'timer.failed': { ru: 'Таймер завершился ошибкой', icon: AlertTriangle },
};

export function getEventMeta(eventType: string): EventMeta | null {
  return EVENT_CATALOG[eventType] ?? null;
}
