/**
 * Next.js standalone output (see Dockerfile: HOSTNAME=0.0.0.0) builds
 * `request.url` / `request.nextUrl` from the server's own bind address
 * instead of the real incoming Host — so behind Caddy every request looks
 * like it came in on http://0.0.0.0:3000. Caddy's reverse_proxy sets
 * X-Forwarded-Host/-Proto from the connection it actually received (and
 * overwrites, rather than trusts, whatever a client sent) as long as
 * `trusted_proxies` isn't configured for the public edge — so behind our
 * own Caddy these headers are safe to read. They're still attacker-facing
 * input if that setup ever changes, or if this ever runs behind something
 * else, so pin them against the one host this deployment actually serves
 * instead of trusting them outright.
 *
 * NEXT_PUBLIC_API_BASE_URL is a required build arg (frontend/Dockerfile)
 * and, in this single-domain deployment, is the site's own origin — Next
 * inlines NEXT_PUBLIC_* vars at build time, in server code too, so this
 * resolves correctly at runtime even though the container gets no matching
 * runtime env (see docker-compose.yml: `web` has no `environment`/`env_file`).
 */
function getAllowedHost(): string | null {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!base) return null;
  try {
    return new URL(base).host.toLowerCase();
  } catch {
    return null;
  }
}

export function getRequestOrigin(request: Request): string {
  const forwardedHost = request.headers.get('x-forwarded-host')?.split(',')[0]?.trim().toLowerCase();
  const forwardedProto = request.headers.get('x-forwarded-proto')?.split(',')[0]?.trim().toLowerCase();
  const allowedHost = getAllowedHost();

  if (
    forwardedHost &&
    (forwardedProto === 'http' || forwardedProto === 'https') &&
    allowedHost &&
    forwardedHost === allowedHost
  ) {
    return `${forwardedProto}://${forwardedHost}`;
  }
  return new URL(request.url).origin;
}
