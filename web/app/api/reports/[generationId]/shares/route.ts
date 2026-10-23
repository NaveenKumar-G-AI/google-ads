import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { authSiteOrigin } from "@/lib/auth-navigation";
import { RecoveryApiError, recoveryApiErrorResponse, recoveryApiJson } from "@/lib/recovery-api-transport";

export async function POST(req: NextRequest, { params }: { params: Promise<{ generationId: string }> }) {
  // Session cookies authenticate this mutation, so verify the browser origin first.
  let origin: string;
  try { origin = authSiteOrigin(process.env.NEXT_PUBLIC_SITE_URL, req.nextUrl.origin); }
  catch { return NextResponse.json({ error: "Service configuration is unavailable." }, { status: 503, headers: { "Cache-Control": "no-store" } }); }
  if (req.headers.get("origin") !== origin || req.headers.get("sec-fetch-site") === "cross-site") {
    return NextResponse.json({ error: "Request origin is not allowed." }, { status: 403 });
  }
  if (req.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
    return NextResponse.json({ error: "A JSON request is required." }, { status: 415 });
  }
  const { generationId } = await params;
  const tenant = req.nextUrl.searchParams.get("tenant");
  if (!tenant) return NextResponse.json({ error: "tenant is required" }, { status: 400 });
  let token: string;
  try {
    const supabase = await createClient();
    const { data: claims, error: claimsError } = await supabase.auth.getClaims();
    if (claimsError || !claims?.claims?.sub) {
      return NextResponse.json({ error: "authentication required" }, { status: 401, headers: { "Cache-Control": "no-store" } });
    }
    const { data: session, error: sessionError } = await supabase.auth.getSession();
    if (sessionError || !session?.session?.access_token) {
      return NextResponse.json({ error: "authentication required" }, { status: 401, headers: { "Cache-Control": "no-store" } });
    }
    token = session.session.access_token;
  } catch {
    return NextResponse.json({ error: "Sign-in verification is temporarily unavailable. Please try again.", code: "AUTH_UNAVAILABLE" }, {
      status: 503, headers: { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" },
    });
  }
  let body: unknown;
  try { body = await req.json(); }
  catch { return NextResponse.json({ error: "Invalid JSON request." }, { status: 400 }); }
  try {
    const result = await recoveryApiJson<{ token?: string }>(
      "/v1/tenants/" + encodeURIComponent(tenant) + "/reports/" + encodeURIComponent(generationId) + "/shares",
      { method: "POST", body: JSON.stringify(body) }, token,
    );
    if (!result || typeof result.token !== "string" || !result.token) {
      throw new RecoveryApiError("The share link was not returned. Refresh the report's share history before trying again.", "API_RESPONSE_INVALID", 502);
    }
    return NextResponse.json(result, { status: 201, headers: { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" } });
  } catch (error) {
    return recoveryApiErrorResponse(error);
  }
}
