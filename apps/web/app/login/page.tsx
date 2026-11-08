import Link from "next/link";

import { LoginForm } from "@/components/login-form";
import { config } from "@/lib/config";
import { supabaseConfigured } from "@/lib/supabase/env";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const { next, error } = await searchParams;

  return (
    <main className="mx-auto max-w-sm px-6 py-16">
      <Link href="/" className="text-sm text-muted-foreground hover:underline">
        ← {config.productName}
      </Link>
      <h1 className="mt-4 text-2xl font-semibold tracking-tight">Sign in</h1>
      <div className="mt-8">
        {supabaseConfigured ? (
          <LoginForm
            next={next}
            initialError={error === "auth" ? "Sign-in didn’t complete. Please try again." : undefined}
          />
        ) : (
          <div role="alert" className="space-y-2 text-sm">
            <p className="text-danger">Supabase isn’t configured yet.</p>
            <p className="text-muted-foreground">
              Add <code className="font-mono">NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
              <code className="font-mono">NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY</code> to{" "}
              <code className="font-mono">apps/web/.env.local</code>, then restart the dev server.
              See <code className="font-mono">docs/AUTH.md</code>.
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
