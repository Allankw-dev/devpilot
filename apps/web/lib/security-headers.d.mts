export interface SecurityHeaderOptions {
  isProd: boolean;
  apiUrl?: string;
  supabaseUrl?: string;
}

export interface HeaderEntry {
  key: string;
  value: string;
}

export function contentSecurityPolicy(options: SecurityHeaderOptions): string;
export function securityHeaders(options: SecurityHeaderOptions): HeaderEntry[];
