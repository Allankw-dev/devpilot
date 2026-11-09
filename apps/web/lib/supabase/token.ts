import { ApiError } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";

/** The current Supabase access token, refreshed automatically by the Supabase client. */
export async function accessToken(): Promise<string> {
  const { data } = await createClient().auth.getSession();
  if (!data.session) throw new ApiError("Not signed in", 401);
  return data.session.access_token;
}
