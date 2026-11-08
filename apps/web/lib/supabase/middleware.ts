import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { supabaseKey, supabaseUrl } from "@/lib/supabase/env";

const PROTECTED_PREFIXES = ["/dashboard"];

function redirectTo(request: NextRequest, source: NextResponse, path: string, search = "") {
  const url = request.nextUrl.clone();
  url.pathname = path;
  url.search = search;
  const redirect = NextResponse.redirect(url);
  // keep any refreshed session cookies on the redirect
  source.cookies.getAll().forEach((c) => redirect.cookies.set(c));
  return redirect;
}

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });
  const path = request.nextUrl.pathname;
  const isProtected = PROTECTED_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`));

  if (!supabaseUrl || !supabaseKey) {
    return isProtected ? redirectTo(request, response, "/login") : response;
  }

  const supabase = createServerClient(supabaseUrl, supabaseKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options),
        );
      },
    },
  });

  // getUser() re-validates the session with Supabase, unlike reading the cookie alone.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user && isProtected) {
    return redirectTo(request, response, "/login", `?next=${encodeURIComponent(path)}`);
  }
  if (user && path === "/login") return redirectTo(request, response, "/dashboard");
  return response;
}
