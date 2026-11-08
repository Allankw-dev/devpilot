export const config = {
  productName: process.env.NEXT_PUBLIC_PRODUCT_NAME ?? "DevPilot AI",
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
} as const;
