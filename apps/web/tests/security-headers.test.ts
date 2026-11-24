import { describe, expect, it } from "vitest";

import { contentSecurityPolicy, securityHeaders } from "@/lib/security-headers.mjs";

const urls = {
  apiUrl: "http://localhost:8001",
  supabaseUrl: "https://abcdefgh.supabase.co",
};

function header(list: { key: string; value: string }[], key: string) {
  return list.find((h) => h.key === key)?.value;
}

describe("securityHeaders", () => {
  it("always sends the basic hardening headers", () => {
    for (const isProd of [true, false]) {
      const list = securityHeaders({ isProd, ...urls });
      expect(header(list, "X-Content-Type-Options")).toBe("nosniff");
      expect(header(list, "Referrer-Policy")).toBe("strict-origin-when-cross-origin");
      expect(header(list, "Permissions-Policy")).toContain("camera=()");
    }
  });

  it("adds framing protection and HSTS only in production", () => {
    const prod = securityHeaders({ isProd: true, ...urls });
    expect(header(prod, "X-Frame-Options")).toBe("DENY");
    expect(header(prod, "Strict-Transport-Security")).toBe("max-age=31536000");

    const dev = securityHeaders({ isProd: false, ...urls });
    expect(header(dev, "X-Frame-Options")).toBeUndefined();
    expect(header(dev, "Strict-Transport-Security")).toBeUndefined();
  });

  it("sends the policy as report-only, never enforced", () => {
    for (const isProd of [true, false]) {
      const list = securityHeaders({ isProd, ...urls });
      expect(header(list, "Content-Security-Policy-Report-Only")).toBeTruthy();
      expect(header(list, "Content-Security-Policy")).toBeUndefined();
    }
  });
});

describe("contentSecurityPolicy", () => {
  it("lets the page talk to its own API and Supabase, and nothing else", () => {
    const csp = contentSecurityPolicy({ isProd: true, ...urls });
    const connect = csp.split("; ").find((d) => d.startsWith("connect-src"));
    expect(connect).toBe(
      "connect-src 'self' http://localhost:8001 https://abcdefgh.supabase.co",
    );
  });

  it("uses only the origin of a configured URL", () => {
    const csp = contentSecurityPolicy({
      isProd: true,
      apiUrl: "https://api.example.com/api/v1/",
    });
    expect(csp).toContain("connect-src 'self' https://api.example.com;");
    expect(csp).not.toContain("/api/v1");
  });

  it("ignores a URL it cannot parse", () => {
    const csp = contentSecurityPolicy({ isProd: true, apiUrl: "not a url", supabaseUrl: undefined });
    expect(csp).toContain("connect-src 'self';");
  });

  it("blocks plugins, base tag tricks and foreign form targets", () => {
    const csp = contentSecurityPolicy({ isProd: true, ...urls });
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).toContain("form-action 'self'");
  });

  it("production forbids framing and eval; development allows eval and the dev websocket", () => {
    const prod = contentSecurityPolicy({ isProd: true, ...urls });
    expect(prod).toContain("frame-ancestors 'none'");
    expect(prod).not.toContain("unsafe-eval");
    expect(prod).not.toContain("ws://");

    const dev = contentSecurityPolicy({ isProd: false, ...urls });
    expect(dev).not.toContain("frame-ancestors");
    expect(dev).toContain("'unsafe-eval'");
    expect(dev).toContain("ws://localhost:*");
  });
});
