/** Authentication redirects use the configured public origin, never proxy headers. */
export function authSiteOrigin(
  configured: string | undefined,
  requestOrigin: string,
  production = process.env.NODE_ENV === "production",
): string {
  const value = configured?.trim() || (production ? "" : requestOrigin);
  if (!value || /[\u0000-\u0020\u007f\\]/.test(value)) {
    throw new Error("Authentication site origin is not configured");
  }
  const url = new URL(value);
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (
    (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) ||
    url.username || url.password || url.search || url.hash ||
    (url.pathname !== "/" && url.pathname !== "")
  ) {
    throw new Error("Authentication site origin must be an HTTPS origin");
  }
  return url.origin;
}
