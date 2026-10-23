import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { authSiteOrigin } from "@/lib/auth-navigation";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const responseHeaders = { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" };
  let origin: string;
  try {
    origin = authSiteOrigin(process.env.NEXT_PUBLIC_SITE_URL, url.origin);
  } catch {
    return new Response("Account confirmation is temporarily unavailable.", {
      status: 503,
      headers: responseHeaders,
    });
  }
  const failure = new URL("/login", origin);
  failure.searchParams.set("error", "This confirmation link could not be completed. Try signing in, or request a new confirmation email.");
  const code = url.searchParams.get("code");
  if (!code || url.searchParams.has("error")) return NextResponse.redirect(failure, { headers: responseHeaders });

  let confirmed = false;
  try {
    const supabase = await createClient();
    const { data, error } = await supabase.auth.exchangeCodeForSession(code);
    confirmed = !error && !!data.session;
  } catch {
    // Auth codes, provider responses and cookies must not appear in logs or URLs.
    console.error("recovery_auth_confirmation_unavailable");
  }
  return NextResponse.redirect(confirmed ? new URL("/onboarding", origin) : failure, { headers: responseHeaders });
}
