import {
  Play,
  Square,
  AlertTriangle,
  MessageSquareX,
  MessageSquarePlus,
  Timer,
  Hourglass,
  Ban,
  RotateCcw,
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
  'agent.context_reset': { ru: 'Контекст сброшен', icon: RotateCcw },
  'model.failed': { ru: 'Модель не ответила', icon: AlertTriangle },
  'turn.failed': { ru: 'Ход завершился ошибкой', icon: AlertTriangle },
  'message.send_failed': { ru: 'Не удалось отправить ответ', icon: MessageSquareX },
  'message.deferred': { ru: 'Ответ отложен: медленный режим', icon: Hourglass },
  'message.write_forbidden': { ru: 'Нет права писать в чате', icon: Ban },
  'message.blocked': { ru: 'Отправка отменена: чат закрыт', icon: MessageSquareX },
  'timer.fired': { ru: 'Сработал отложенный таймер', icon: Timer },
  'timer.failed': { ru: 'Таймер завершился ошибкой', icon: AlertTriangle },
  'first_comment.sent': { ru: 'Первый комментарий отправлен', icon: MessageSquarePlus },
  'first_comment.failed': { ru: 'Первый комментарий не ушёл', icon: AlertTriangle },
};

export function getEventMeta(eventType: string): EventMeta | null {
  return EVENT_CATALOG[eventType] ?? null;
}
