import {
  CLIENT_MARKETING_EVENTS,
  SERVER_MARKETING_EVENTS,
  isMarketingEventSource,
  type MarketingEvent,
  type MarketingEventSource,
} from "@/lib/marketing-analytics";

type PrivacyHeaders = Pick<Headers, "get">;

export function marketingPrivacyOptOut(headers: PrivacyHeaders): boolean {
  return headers.get("dnt") === "1" || headers.get("sec-gpc") === "1";
}

/**
 * First-party structured log sink. No visitor identifiers or arbitrary properties.
 * Hosting access logs and their retention are a separate operator responsibility.
 * Call confirmed conversion events from the successful server operation only.
 */
export function recordMarketingEvent(
  event: MarketingEvent,
  source: MarketingEventSource = "unspecified",
  requestHeaders?: PrivacyHeaders,
): void {
  try {
    if (requestHeaders && marketingPrivacyOptOut(requestHeaders)) return;
    if (![...CLIENT_MARKETING_EVENTS, ...SERVER_MARKETING_EVENTS].some((allowed) => allowed === event) || !isMarketingEventSource(source)) return;
    console.info(JSON.stringify({ type: "recovery_marketing", version: 1, event, source, timestamp: new Date().toISOString() }));
  } catch { /* Logging must never alter an authentication or onboarding result. */ }
}
