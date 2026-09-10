import { NextResponse } from 'next/server';

/**
 * Liveness probe for the Docker HEALTHCHECK (see frontend/Dockerfile).
 * Must stay dependency-free and must bypass `middleware.ts`.
 */
export async function GET() {
  return NextResponse.json({ ok: true });
}
