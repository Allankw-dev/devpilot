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
