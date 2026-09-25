"use server";

import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { requireServerEnv } from "@/server/env";

export async function signInWithGoogle() {
  const supabase = await createClient();
  const appUrl = requireServerEnv("FOCUSOS_APP_URL");
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: new URL("/auth/callback", appUrl).toString(),
    },
  });

  if (error || !data.url) {
    redirect("/?authError=start");
  }

  redirect(data.url);
}

export async function signOut() {
  const supabase = await createClient();
  const { error } = await supabase.auth.signOut({ scope: "local" });

  if (error) {
    redirect("/?authError=logout");
  }

  redirect("/");
}
