/**
 * Квотирует каждый сегмент storage-пути для URL. Новые записи приходят уже
 * безопасными (бэкенд санитайзит имена), но у исторических строк в имени могли
 * остаться `#`, `?`, пробелы — без квотирования такой путь обрежется на `#`.
 */
export function encodeMediaPath(storagePath: string): string {
  return storagePath
    .split('/')
    .map((segment) => encodeURIComponent(segment))
    .join('/');
}
