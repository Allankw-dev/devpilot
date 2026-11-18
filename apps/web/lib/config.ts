export const config = {
  productName: process.env.NEXT_PUBLIC_PRODUCT_NAME ?? "DevPilot AI",
  docsUrl:
    process.env.NEXT_PUBLIC_DOCS_URL ?? "https://github.com/Allankw-dev/devpilot/tree/main/docs",
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001",
} as const;
