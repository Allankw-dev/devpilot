import { createBrowserClient } from "@supabase/ssr";

import { supabaseKey, supabaseUrl } from "@/lib/supabase/env";

export function createClient() {
  if (!supabaseUrl || !supabaseKey) {
    throw new Error(
      "Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY.",
    );
  }
  return createBrowserClient(supabaseUrl, supabaseKey);
}
