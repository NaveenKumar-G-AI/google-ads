import type { MetadataRoute } from "next";
export default function sitemap(): MetadataRoute.Sitemap {
  try { const origin=new URL(process.env.NEXT_PUBLIC_SITE_URL || ""); if(origin.protocol!=="https:") return []; return ["/","/product","/for-agencies","/for-brands","/reporting","/security","/pricing","/demo"].map(route=>({url:new URL(route,origin).href})); } catch {return [];}
}
