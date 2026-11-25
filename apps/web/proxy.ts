import type { NextRequest } from "next/server";

import { updateSession } from "@/lib/supabase/middleware";

// Next 16 calls this file a "proxy" (it was "middleware"): it refreshes the sign-in session on
// every page request.
export async function proxy(request: NextRequest) {
  return updateSession(request);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
