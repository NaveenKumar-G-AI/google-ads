import "server-only";

import { getPublicLaunchStatus } from "@/lib/recovery-api";

/** Only explicitly configured public destinations are presented to visitors. */
export function safeHttpsUrl(value: string | undefined | null): string | null {
  if (!value || value.length > 2048 || /[\u0000-\u0020\u007f]/.test(value)) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || !url.hostname || url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

function safeEmail(value: string | undefined): string | null {
  if (!value || value.length > 254) return null;
  const email = value.trim();
  return /^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?)+$/i.test(email)
    ? email
    : null;
}

export function getMarketingConfig() {
  return {
    reviewBookingUrl: safeHttpsUrl(process.env.RECOVERY_REVIEW_BOOKING_URL),
    supportEmail: safeEmail(process.env.RECOVERY_SUPPORT_EMAIL),
    statusUrl: safeHttpsUrl(process.env.RECOVERY_STATUS_URL),
    dataDeletionUrl: safeHttpsUrl(process.env.RECOVERY_DATA_DELETION_URL),
    siteUrl: safeHttpsUrl(process.env.NEXT_PUBLIC_SITE_URL),
  };
}

export function supportMailto(subject: string): string | null {
  const email = getMarketingConfig().supportEmail;
  if (!email) return null;
  const separator = email.lastIndexOf("@");
  const recipient = `${encodeURIComponent(email.slice(0, separator))}@${email.slice(separator + 1)}`;
  return `mailto:${recipient}?subject=${encodeURIComponent(subject)}`;
}

export type PublishedLegalDocument = { url: string; version: string };

/** Legal identity comes from the same API contract used by workspace onboarding. */
export async function getPublishedLegalDocument(
  kind: "terms" | "privacy",
): Promise<PublishedLegalDocument | null> {
  try {
    const launch = await getPublicLaunchStatus(AbortSignal.timeout(1800));
    if (!launch) return null;
    const url = safeHttpsUrl(kind === "terms" ? launch.terms_url : launch.privacy_url);
    const version = kind === "terms" ? launch.terms_version : launch.privacy_version;
    if (!url || !version?.trim()) return null;

    // A local availability page is not a substitute for an actual published policy.
    const siteUrl = getMarketingConfig().siteUrl;
    if (siteUrl) {
      const policy = new URL(url);
      if (policy.origin === new URL(siteUrl).origin && policy.pathname.replace(/\/$/, "") === `/${kind}`) return null;
    }
    return { url, version };
  } catch {
    return null;
  }
}
