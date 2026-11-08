import type { Metadata } from "next";

import { Providers } from "@/components/providers";
import { config } from "@/lib/config";

import "./globals.css";

export const metadata: Metadata = {
  title: config.productName,
  description: "AI-powered developer productivity platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
