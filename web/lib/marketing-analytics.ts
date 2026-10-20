/** Fixed funnel vocabulary. Never pass account data, URLs or form values here. */
export const CLIENT_MARKETING_EVENTS = [
  "hero_cta_click",
  "secondary_hero_cta_click",
  "product_tour_open",
  "product_tour_complete",
  "agency_cta_click",
  "brand_cta_click",
  "pricing_open",
  "security_page_open",
  "connect_google_ads_click",
  "book_review_click",
] as const;

export const SERVER_MARKETING_EVENTS = [
  "signup_started",
  "signup_completed",
  "oauth_connection_started",
  "oauth_connected",
] as const;

export const MARKETING_EVENT_SOURCES = [
  "hero", "header", "footer", "homepage", "product", "product_tour",
  "for_agencies", "for_brands", "pricing", "security", "reporting",
  "final_cta", "recovery_review", "signup", "onboarding", "oauth_callback",
  "connect", "unspecified",
] as const;

export type ClientMarketingEvent = (typeof CLIENT_MARKETING_EVENTS)[number];
export type MarketingEvent = ClientMarketingEvent | (typeof SERVER_MARKETING_EVENTS)[number];
export type MarketingEventSource = (typeof MARKETING_EVENT_SOURCES)[number];

export function isClientMarketingEvent(value: unknown): value is ClientMarketingEvent {
  return typeof value === "string" && (CLIENT_MARKETING_EVENTS as readonly string[]).includes(value);
}

export function isMarketingEventSource(value: unknown): value is MarketingEventSource {
  return typeof value === "string" && (MARKETING_EVENT_SOURCES as readonly string[]).includes(value);
}

/** Cookie-free, best-effort telemetry. It must never delay navigation or signup. */
export function trackMarketingEvent(event: ClientMarketingEvent, source: MarketingEventSource = "unspecified"): void {
  if (typeof window === "undefined" || !isClientMarketingEvent(event) || !isMarketingEventSource(source)) return;
  const preferences = navigator as Navigator & { globalPrivacyControl?: boolean; msDoNotTrack?: string };
  const legacyWindow = window as Window & { doNotTrack?: string };
  if (preferences.globalPrivacyControl || preferences.doNotTrack === "1" || preferences.msDoNotTrack === "1" || legacyWindow.doNotTrack === "1") return;
  try {
    void fetch("/api/marketing/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event, source }),
      credentials: "omit",
      referrerPolicy: "no-referrer",
      mode: "same-origin",
      keepalive: true,
    }).catch(() => { /* Analytics failure cannot interrupt the product. */ });
  } catch { /* Browsers may disable requests or exhaust their keepalive budget. */ }
}
