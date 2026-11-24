import { securityHeaders } from "./lib/security-headers.mjs";

const isProd = process.env.NODE_ENV === "production";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders({
          isProd,
          apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001",
          supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL,
        }),
      },
    ];
  },
};

export default nextConfig;
