const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const WS_URL = (process.env.NEXT_PUBLIC_WS_URL || API_URL.replace(/^http/, "ws")).replace(/\/$/, "");
export const TOKEN_KEY = "meridian_token";

export class ApiError extends Error {
  status: number;
  requestId?: string;
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown, requestId?: string) {
    super(message);
    this.status = status;
    this.detail = detail;
    this.requestId = requestId;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

function newRequestId(): string {
  const random = Math.random().toString(16).slice(2).padEnd(12, "0");
  return `req_web_${Date.now().toString(16)}${random}`;
}

async function parseError(response: Response): Promise<ApiError> {
  let payload: any = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const detail = payload?.detail ?? payload?.title ?? response.statusText;
  const message =
    typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((item: any) => item.msg || JSON.stringify(item)).join("; ")
        : `Request failed (${response.status})`;
  return new ApiError(response.status, message, detail, payload?.request_id ?? response.headers.get("x-request-id") ?? undefined);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("X-Request-ID", newRequestId());
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_URL}/api/v1${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (response.status === 401) {
    clearToken();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    }
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  baseUrl: API_URL,
  wsUrl: WS_URL,
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: async <T>(path: string, file: File): Promise<T> => {
    const token = getToken();
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`${API_URL}/api/v1${path}`, {
      method: "POST",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "X-Request-ID": newRequestId(),
      },
      body: form,
    });
    if (!response.ok) throw await parseError(response);
    return (await response.json()) as T;
  },
};

export function terminalUrl(token: string): string {
  return `${WS_URL}/api/v1/ws/terminal?token=${encodeURIComponent(token)}`;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.requestId ? `${error.message} · request ${error.requestId}` : error.message;
  }
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}
