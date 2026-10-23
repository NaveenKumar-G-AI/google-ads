import { NextRequest, NextResponse } from "next/server";
import { recoveryApiBody, recoveryApiErrorResponse, recoveryApiRequest } from "@/lib/recovery-api-transport";

export async function GET(_: NextRequest, { params }: { params: Promise<{ token: string; format: string }> }) {
  const { token, format } = await params;
  if (!["pdf", "csv"].includes(format)) return NextResponse.json({ error: "invalid format" }, { status: 400 });
  try {
    const response = await recoveryApiRequest("/v1/public/report-shares/" + encodeURIComponent(token) + "/artifact/" + format);
    return new NextResponse(await recoveryApiBody(response), {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") || "application/octet-stream",
        "Content-Disposition": response.headers.get("content-disposition") || 'attachment; filename="shared-report.' + format + '"',
        "Cache-Control": "private, no-store",
        "Referrer-Policy": "no-referrer",
      },
    });
  } catch (error) {
    return recoveryApiErrorResponse(error);
  }
}
