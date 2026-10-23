import "server-only";

export class RecoveryApiError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly requestId: string | null;

  constructor(message: string, code: string, status: number | null = null, requestId: string | null = null) {
    super(message);
    this.name = "RecoveryApiError";
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

function configurationError(code: string): never {
  throw new RecoveryApiError("Recovery OS cannot connect to its service because the deployment configuration is incomplete. Contact support.", code);
}

/** Resolve at request time: a public build must not need an authenticated API. */
export function recoveryApiOrigin(
  raw = process.env.RECOVERY_API_BASE_URL,
  production = process.env.NODE_ENV === "production",
): string {
  if (!raw?.trim()) {
    if (production) configurationError("API_ORIGIN_MISSING");
    return "http://127.0.0.1:8000";
  }
  const value = raw.trim();
  if (/[\u0000-\u0020\u007f\\]/.test(value)) configurationError("API_ORIGIN_INVALID");
  let url: URL;
  try { url = new URL(value); } catch { configurationError("API_ORIGIN_INVALID"); }
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (
    !["http:", "https:"].includes(url.protocol) || !url.hostname ||
    (production && url.protocol === "http:" && !loopback) ||
    url.username || url.password || url.search || url.hash || !/^\/+$/.test(url.pathname)
  ) configurationError("API_ORIGIN_INVALID");
  return url.origin;
}

export function recoveryApiUrl(path: string): string {
  // Never let a path replace the configured origin or carry URL credentials.
  if (!path.startsWith("/") || path.startsWith("//") || /[\\\r\n#]/.test(path)) {
    configurationError("API_PATH_INVALID");
  }
  return `${recoveryApiOrigin()}${path}`;
}

function responseError(response: Response): RecoveryApiError {
  const status = response.status;
  const candidate = response.headers.get("x-request-id");
  const requestId = candidate && /^[0-9a-f-]{36}$/i.test(candidate) ? candidate : null;
  const messages: Record<number, string> = {
    400: "Check the information you entered and try again.",
    401: "Your session is no longer authorized. Sign in again.",
    402: "An active subscription is required for this action. Check your subscription status.",
    403: "You do not have permission to perform this action.",
    404: "The requested item or service endpoint is unavailable. Refresh the page; contact support if this continues.",
    409: "This action conflicts with the current workspace state. Refresh its status before trying again.",
    422: "Check the information you entered and try again.",
    429: "The service is receiving too many requests. Wait a moment before trying again.",
  };
  return new RecoveryApiError(
    messages[status] ?? "Recovery OS could not complete the request. Refresh its status before trying again.",
    `API_HTTP_${status}`, status, requestId,
  );
}

/** One attempt only: provider callbacks and mutation requests must not be replayed. */
export async function recoveryApiRequest(path: string, init: RequestInit = {}, token?: string): Promise<Response> {
  const url = recoveryApiUrl(path);
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const timeout = AbortSignal.timeout(30_000);
  const signal = init.signal ? AbortSignal.any([init.signal, timeout]) : timeout;
  let response: Response;
  try {
    response = await fetch(url, { ...init, headers, cache: "no-store", redirect: "error", signal });
  } catch {
    throw new RecoveryApiError(
      signal.aborted
        ? "Recovery OS did not respond in time. Refresh the status before submitting the action again."
        : "Recovery OS is temporarily unreachable. Try loading the page again in a moment.",
      signal.aborted ? "API_TIMEOUT" : "API_UNREACHABLE",
    );
  }
  if (!response.ok) throw responseError(response);
  return response;
}

export async function recoveryApiJson<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const response = await recoveryApiRequest(path, init, token);
  if (response.status === 204) return undefined as T;
  try {
    return await response.json() as T;
  } catch {
    throw new RecoveryApiError(
      "Recovery OS returned an unreadable response. Refresh the status before trying again.",
      "API_RESPONSE_INVALID", response.status,
    );
  }
}

/** Read before sending response headers, so an interrupted download cannot look successful. */
export async function recoveryApiBody(response: Response): Promise<ArrayBuffer> {
  try {
    return await response.arrayBuffer();
  } catch {
    throw new RecoveryApiError(
      "Recovery OS could not finish the download. Try loading it again.",
      "API_DOWNLOAD_INTERRUPTED", 502,
    );
  }
}

/** Only deliberate, sanitized service errors may be shown by action forms. */
export function recoveryApiErrorMessage(error: unknown): string {
  if (!(error instanceof RecoveryApiError)) throw error;
  return error.requestId ? `${error.message} Reference: ${error.requestId}` : error.message;
}

export function recoveryApiErrorResponse(error: unknown): Response {
  if (!(error instanceof RecoveryApiError)) throw error;
  return Response.json(
    { error: recoveryApiErrorMessage(error), code: error.code },
    { status: error.status && error.status >= 400 ? error.status : 503, headers: { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" } },
  );
}
