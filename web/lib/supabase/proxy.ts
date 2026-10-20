import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });
  // Public product storytelling must not depend on an auth service or its secrets.
  // Protected routes continue through the original session refresh below.
  const publicPaths = new Set([
    "/", "/product", "/for-agencies", "/for-brands", "/reporting", "/security",
    "/pricing", "/demo", "/product-tour", "/how-it-works", "/recovery-review",
    "/terms", "/privacy", "/status", "/data-deletion", "/api/marketing/events",
    "/robots.txt", "/sitemap.xml",
  ]);
  const pathname = request.nextUrl.pathname.replace(/\/$/, "") || "/";
  if (publicPaths.has(pathname)) return response;
  if (["/connect", "/signup", "/login"].includes(pathname)
    && (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY)) return response;
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
        }
      }
    }
  );
  await supabase.auth.getClaims();
  return response;
}
