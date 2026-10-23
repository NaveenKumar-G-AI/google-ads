import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { authSiteOrigin } from "@/lib/auth-navigation";
import { recordMarketingEvent } from "@/lib/marketing-analytics-server";
import { RecoveryApiError, recoveryApiErrorMessage, recoveryApiJson } from "@/lib/recovery-api-transport";

export async function GET(request: Request) {
  const url = new URL(request.url);
  let origin: string;
  try { origin = authSiteOrigin(process.env.NEXT_PUBLIC_SITE_URL, url.origin); }
  catch { return NextResponse.json({ error: "Service configuration is unavailable." }, { status: 503, headers: { "Cache-Control": "no-store" } }); }
  const failure = (message: string) => {
    const target = new URL("/onboarding", origin);
    target.searchParams.set("oauth_error", message);
    return NextResponse.redirect(target, { headers: { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" } });
  };
  if (url.searchParams.has("error")) return failure("Google authorization was not completed. You can reconnect from onboarding.");
  const code = url.searchParams.get("code"), state = url.searchParams.get("state");
  if (!code || !state) return failure("Google authorization is missing callback information. Reconnect from onboarding.");
  const login = () => NextResponse.redirect(new URL("/login", origin), { headers: { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" } });
  let token: string;
  try {
    const supabase = await createClient();
    const { data: claims, error: claimsError } = await supabase.auth.getClaims();
    if (claimsError || !claims?.claims?.sub) return login();
    const { data: session, error: sessionError } = await supabase.auth.getSession();
    if (sessionError || !session?.session?.access_token) return login();
    token = session.session.access_token;
  } catch {
    // Authentication outages must not consume or replay Google's one-use code.
    return failure("Your sign-in could not be verified. Try signing in again, then reconnect Google Ads from onboarding.");
  }
  let result: { return_path?: string; tenant_id: string; discovery_job: { job_id: string } };
  try {
    result = await recoveryApiJson("/v1/onboarding/google-ads/oauth/callback", {
      method: "POST", body: JSON.stringify({ code, state }),
    }, token);
  } catch (error) {
    if (error instanceof RecoveryApiError && error.status === 401) return login();
    return failure(recoveryApiErrorMessage(error));
  }
  // A connection needs the backend's tenant and discovery receipt before success is shown.
  if (!result || typeof result.tenant_id !== "string" || !result.tenant_id ||
      typeof result.discovery_job?.job_id !== "string" || !result.discovery_job.job_id) {
    return failure("Google returned an incomplete connection result. Refresh onboarding to check its status.");
  }
  const path = result.return_path || "/onboarding";
  if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//") || /[\u0000-\u0020\u007f\\]/.test(path)) {
    return failure("The connection return path is invalid. Refresh onboarding to check its status.");
  }
  const target = new URL(path, origin);
  if (target.origin !== origin) return failure("The connection return path is invalid. Refresh onboarding to check its status.");
  target.searchParams.set("tenant", result.tenant_id);
  target.searchParams.set("discovery_job", result.discovery_job.job_id);
  recordMarketingEvent("oauth_connected", "oauth_callback", request.headers);
  return NextResponse.redirect(target, { headers: { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" } });
}
