import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { recoveryApiBody, recoveryApiErrorResponse, recoveryApiRequest } from "@/lib/recovery-api-transport";

export async function GET(req: NextRequest) {
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
  try {
    const response = await recoveryApiRequest(
      "/v1/tenants/" + encodeURIComponent(tenant) + "/security-data/configuration-export",
      {}, token,
    );
    return new NextResponse(await recoveryApiBody(response), {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") || "application/json; charset=utf-8",
        "Content-Disposition": response.headers.get("content-disposition") || 'attachment; filename="recovery-os-configuration.json"',
        "Cache-Control": "private, no-store",
        "Referrer-Policy": "no-referrer",
      },
    });
  } catch (error) {
    return recoveryApiErrorResponse(error);
  }
}
