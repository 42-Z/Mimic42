export function getLoginRedirect(value: string | null): string {
  const fallback = '/dashboard';
  if (!value?.startsWith('/') || value.startsWith('//') || /[\\\x00-\x1f\x7f]/.test(value)) {
    return fallback;
  }

  const [pathname = ''] = value.split(/[?#]/, 1);
  if (/%(?:2f|5c|0[0-9a-f]|1[0-9a-f]|7f|25)/i.test(pathname)) {
    return fallback;
  }

  try {
    decodeURIComponent(pathname);
    const base = 'https://internal.invalid';
    const url = new URL(value, base);
    if (url.origin !== base || url.pathname.startsWith('//')) return fallback;
    return value;
  } catch {
    return fallback;
  }
}
