import { isClientMarketingEvent, isMarketingEventSource } from "@/lib/marketing-analytics";
import { marketingPrivacyOptOut, recordMarketingEvent } from "@/lib/marketing-analytics-server";

const MAX_BODY_BYTES = 512;
const response = (status: number) => new Response(null, { status, headers: { "Cache-Control": "no-store" } });

function expectedOrigin(request: Request): string | null {
  const configured = process.env.NEXT_PUBLIC_SITE_URL;
  if (configured) {
    // A configured public origin is authoritative behind a reverse proxy.
    if (configured.length > 2048 || /[\u0000-\u0020\u007f]/.test(configured)) return null;
    try {
      const url = new URL(configured);
      return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.origin : null;
    } catch { return null; }
  }
  const url = new URL(request.url);
  if (!["http:", "https:"].includes(url.protocol)) return null;
  const host = request.headers.get("host");
  if (host === null) return url.origin;
  // Next can normalize Request.url to localhost. Use the actual HTTP Host,
  // with no credentials, paths, whitespace, list values or forwarded overrides.
  if (!/^(?:[a-zA-Z0-9.-]+|\[[0-9a-fA-F:.]+\])(?::[0-9]{1,5})?$/.test(host)) return null;
  try { return new URL(`${url.protocol}//${host}`).origin; }
  catch { return null; }
}

export async function POST(request: Request): Promise<Response> {
  // No cross-site submissions, credentials, CORS allowance or arbitrary event data.
  const origin = expectedOrigin(request);
  if (!origin || request.headers.get("origin") !== origin) return response(403);
  const fetchSite = request.headers.get("sec-fetch-site");
  if (fetchSite && fetchSite !== "same-origin") return response(403);
  if (marketingPrivacyOptOut(request.headers)) return response(204);
  if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") return response(415);
  const statedLength = request.headers.get("content-length");
  if (statedLength && (!/^\d+$/.test(statedLength) || Number(statedLength) > MAX_BODY_BYTES)) return response(413);
  if (!request.body) return response(400);

  // Enforce the cap even for streamed requests without a Content-Length header.
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let byteLength = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      byteLength += chunk.value.byteLength;
      if (byteLength > MAX_BODY_BYTES) {
        await reader.cancel();
        return response(413);
      }
      chunks.push(chunk.value);
    }
  } catch {
    return response(400);
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(byteLength);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let body: unknown;
  try { body = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { return response(400); }
  if (!body || typeof body !== "object" || Array.isArray(body)) return response(400);
  const payload = body as Record<string, unknown>;
  if (Object.keys(payload).some((key) => key !== "event" && key !== "source")) return response(400);
  const source = payload.source ?? "unspecified";
  // Signup/OAuth confirmations cannot be manufactured by this browser endpoint.
  if (!isClientMarketingEvent(payload.event) || !isMarketingEventSource(source)) return response(400);
  recordMarketingEvent(payload.event, source, request.headers);
  return response(204);
}
