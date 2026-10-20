import type { MetadataRoute } from "next";
export default function robots(): MetadataRoute.Robots {
  let sitemap: string | undefined;
  try { const origin = new URL(process.env.NEXT_PUBLIC_SITE_URL || ""); if(origin.protocol === "https:") sitemap = new URL("/sitemap.xml", origin).href; } catch { /* Local preview has no public canonical origin. */ }
  return { rules: { userAgent: "*", allow: "/", disallow: ["/app", "/api", "/internal", "/onboarding", "/connect", "/login", "/signup", "/shared/", "/accept-invite/"] }, ...(sitemap ? {sitemap} : {}) };
}
