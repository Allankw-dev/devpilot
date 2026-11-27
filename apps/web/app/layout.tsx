import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

import type { Metadata } from "next";

import { Providers } from "@/components/providers";
import { config } from "@/lib/config";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: config.productName,
  description: "AI-powered developer productivity platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // The inline script sets the saved theme before the first paint, so there is no flash.
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
