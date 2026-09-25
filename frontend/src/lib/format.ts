import { format, isValid, parseISO } from 'date-fns';
import { ru } from 'date-fns/locale';

/**
 * Компактная запись крупных счётчиков: 12 300 → «12,3 тыс»,
 * 1 200 000 → «1,2 млн». Малые значения округляются до целого,
 * некорректный ввод схлопывается в ноль.
 */
export function formatCompactNumber(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return '0';
  }
  if (value < 1_000) {
    return Math.round(value).toString();
  }
  const thousands = value / 1_000;
  if (thousands < 1_000) {
    const rounded = thousands < 100 ? thousands.toFixed(1) : thousands.toFixed(0);
    if (Number(rounded) < 1_000) {
      return `${rounded.replace('.', ',')} тыс`;
    }
  }
  return `${(value / 1_000_000).toFixed(1).replace('.', ',')} млн`;
}

/** Разбирает строку вида YYYY-MM-DD; всё прочее считается не датой. */
function parseDay(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = parseISO(value);
  return isValid(parsed) ? parsed : null;
}

/**
 * Короткая русская подпись дня для оси графика: «2026-09-25» → «25.09».
 * Нераспознанное значение отдаётся как есть, чтобы не терять данные.
 */
export function formatDayLabel(value: string | null | undefined): string {
  const day = parseDay(value);
  return day ? format(day, 'dd.MM') : (value ?? '');
}

/**
 * Полная русская подпись дня для тултипа: «2026-09-25» → «25 сентября 2026».
 */
export function formatDayFull(value: string | null | undefined): string {
  const day = parseDay(value);
  return day ? format(day, 'd MMMM yyyy', { locale: ru }) : (value ?? '');
}
