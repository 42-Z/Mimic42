/**
 * Перемещение роверного фокуса внутри горизонтального списка вкладок
 * (WAI-ARIA APG, manual activation): стрелки ходят по кругу, Home/End — к краям,
 * а Enter/Space обрабатываются отдельно как активация.
 */
export function nextTabFocusIndex(key: string, current: number, length: number): number | null {
  if (length <= 0 || current < 0 || current >= length) return null;
  switch (key) {
    case 'ArrowRight':
      return (current + 1) % length;
    case 'ArrowLeft':
      return (current - 1 + length) % length;
    case 'Home':
      return 0;
    case 'End':
      return length - 1;
    default:
      return null;
  }
}
