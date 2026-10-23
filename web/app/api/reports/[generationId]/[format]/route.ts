import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { recoveryApiBody, recoveryApiErrorResponse, recoveryApiRequest } from "@/lib/recovery-api-transport";

export async function GET(req: NextRequest, { params }: { params: Promise<{ generationId: string; format: string }> }) {
  const { generationId, format } = await params;
  if (!["pdf", "csv"].includes(format)) return NextResponse.json({ error: "invalid format" }, { status: 400 });
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
      "/v1/tenants/" + encodeURIComponent(tenant) + "/reports/" + encodeURIComponent(generationId) + "/artifact/" + format,
      {}, token,
    );
    return new NextResponse(await recoveryApiBody(response), {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") || "application/octet-stream",
        "Content-Disposition": response.headers.get("content-disposition") || 'attachment; filename="report.' + format + '"',
        "X-Artifact-SHA256": response.headers.get("x-artifact-sha256") || "",
        "Cache-Control": "private, no-store",
        "Referrer-Policy": "no-referrer",
      },
    });
  } catch (error) {
    return recoveryApiErrorResponse(error);
  }
}
