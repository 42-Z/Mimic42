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
