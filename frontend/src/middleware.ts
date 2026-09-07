import { type NextRequest, NextResponse } from 'next/server';
import { createServerClient, type CookieOptions } from '@supabase/ssr';
import type { Database } from '@/types/supabase';

// Public routes that don't require authentication
const PUBLIC_PATHS = ['/login', '/register', '/auth/callback', '/reset-password', '/update-password'];

// Routes that should redirect authenticated users away
const AUTH_ONLY_PATHS = ['/login', '/register', '/reset-password'];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Skip middleware for API routes, static files, etc.
  if (
    pathname.startsWith('/_next') ||
    pathname.startsWith('/api/auth') ||
    pathname.includes('.') // static files
  ) {
    return NextResponse.next();
  }

  let response = NextResponse.next({
    request: {
      headers: request.headers,
    },
  });

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

  const supabase = createServerClient<Database>(supabaseUrl, supabaseAnonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet: { name: string; value: string; options?: CookieOptions }[]) {
        cookiesToSet.forEach(({ name, value }) =>
          request.cookies.set(name, value)
        );
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options)
        );
      },
    },
  });

  // Refresh the session if expired — important for keeping users logged in
  const { data: { user }, error } = await supabase.auth.getUser();

  const isPublicPath = PUBLIC_PATHS.some((p) => pathname.startsWith(p));
  const isAuthOnlyPath = AUTH_ONLY_PATHS.some((p) => pathname.startsWith(p));

  // ── No session ────────────────────────────────────────────────────────────
  if (!user || error) {
    if (!isPublicPath) {
      const loginUrl = new URL('/login', request.url);
      loginUrl.searchParams.set('redirect', pathname);
      return NextResponse.redirect(loginUrl);
    }
    return response;
  }

  // ── Has session, trying to access auth pages → redirect to dashboard ─────
  if (isAuthOnlyPath) {
    return NextResponse.redirect(new URL('/dashboard', request.url));
  }

  // ── Check if onboarding is complete ───────────────────────────────────────
  // Only check when navigating to protected dashboard routes (not onboarding itself)
  if (!pathname.startsWith('/onboarding') && !isPublicPath) {
    const { data: agents, error: agentsError } = await supabase
      .from('agents')
      .select('id')
      .eq('owner_id', user.id)
      .limit(1);

    if (!agentsError && (!agents || agents.length === 0)) {
      // No agents exist yet — redirect to onboarding
      return NextResponse.redirect(new URL('/onboarding', request.url));
    }
  }

  return response;
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static files)
     * - _next/image (image optimization)
     * - favicon.ico
     * - public folder
     */
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
};
