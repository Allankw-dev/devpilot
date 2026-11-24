// Security headers for the web app. Plain .mjs because next.config.mjs can't import TypeScript.
//
// The Content-Security-Policy is sent as REPORT-ONLY: the browser lists what it would have blocked
// in the developer console, but blocks nothing yet. It still allows inline scripts (Next.js needs
// them without a per-request nonce), so even enforced it is a partial defence. See docs/SECURITY.md.

/** @param {string | undefined} url */
function originOf(url) {
  if (!url) return undefined;
  try {
    return new URL(url).origin;
  } catch {
    return undefined;
  }
}

/**
 * @param {{ isProd: boolean, apiUrl?: string, supabaseUrl?: string }} options
 * @returns {string}
 */
export function contentSecurityPolicy({ isProd, apiUrl, supabaseUrl }) {
  const connect = ["'self'", originOf(apiUrl), originOf(supabaseUrl)].filter(Boolean);
  // `next dev` needs eval for hot reload and a websocket back to the dev server.
  if (!isProd) connect.push("ws://localhost:*", "ws://127.0.0.1:*");
  const scripts = isProd ? "'self' 'unsafe-inline'" : "'self' 'unsafe-inline' 'unsafe-eval'";

  const directives = [
    "default-src 'self'",
    `script-src ${scripts}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src ${connect.join(" ")}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ];
  // Not in development: VS Code's built-in browser shows pages inside a frame.
  if (isProd) directives.push("frame-ancestors 'none'");
  return directives.join("; ");
}

/**
 * @param {{ isProd: boolean, apiUrl?: string, supabaseUrl?: string }} options
 * @returns {{ key: string, value: string }[]}
 */
export function securityHeaders(options) {
  const headers = [
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
    { key: "Content-Security-Policy-Report-Only", value: contentSecurityPolicy(options) },
  ];
  if (options.isProd) {
    // Production only: HTTPS is not available on localhost, and the dev server is shown in a frame.
    headers.push({ key: "X-Frame-Options", value: "DENY" });
    headers.push({ key: "Strict-Transport-Security", value: "max-age=31536000" });
  }
  return headers;
}
