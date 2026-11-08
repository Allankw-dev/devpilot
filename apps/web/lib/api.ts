import { config } from "@/lib/config";

export type ServiceStatus = "ok" | "down";

export interface HealthResponse {
  status: "ok" | "degraded";
  product: string;
  environment: string;
  database: ServiceStatus;
  redis: ServiceStatus;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${config.apiUrl}/api/v1${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  // /health returns a valid JSON body on 503 too, so only fail on unparseable responses
  const body = await res.json().catch(() => null);
  if (body === null) throw new ApiError(`Request failed: ${res.status}`, res.status);
  return body as T;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
};

// ---------- authenticated endpoints ----------

export type Role = "viewer" | "member" | "admin" | "owner";

export interface OrgWithRole {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  role: Role;
}

export interface Me {
  user: { id: string; email: string; display_name: string | null };
  organizations: OrgWithRole[];
}

async function authed<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${config.apiUrl}/api/v1${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`;
    throw new ApiError(detail, res.status);
  }
  return body as T;
}

export const authedApi = {
  me: (token: string) => authed<Me>("/me", token),
  createOrg: (token: string, name: string) =>
    authed<OrgWithRole>("/orgs", token, { method: "POST", body: JSON.stringify({ name }) }),
};
