import "server-only";

import { createClient } from "@/lib/supabase/server";
import { getServerUser } from "@/server/auth/session";
import { requireServerEnv } from "@/server/env";

export type WorkingHours = {
  days: number[];
  start_minute: number;
  end_minute: number;
};

export type Profile = {
  id: string;
  timezone: string;
  working_hours: WorkingHours;
};

type ReadResult =
  | { kind: "ok"; profile: Profile | null }
  | { kind: "unauthorized" }
  | { kind: "unavailable" };

type SaveResult = "ok" | "unauthorized" | "invalid" | "unavailable";

async function verifiedAccessToken(): Promise<string | null> {
  const user = await getServerUser();
  if (!user) return null;

  const supabase = await createClient();
  const { data, error } = await supabase.auth.getSession();
  if (error || !data.session) return null;
  return data.session.access_token;
}

function profileUrl(): URL {
  return new URL("/profile", requireServerEnv("FOCUSOS_API_URL"));
}

export async function readProfile(): Promise<ReadResult> {
  const token = await verifiedAccessToken();
  if (!token) return { kind: "unauthorized" };

  try {
    const response = await fetch(profileUrl(), {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    if (response.status === 401) return { kind: "unauthorized" };
    if (!response.ok) return { kind: "unavailable" };
    const result = (await response.json()) as { profile: Profile | null };
    return { kind: "ok", profile: result.profile };
  } catch {
    return { kind: "unavailable" };
  }
}

export async function writeProfile(
  profile: Omit<Profile, "id">,
): Promise<SaveResult> {
  const token = await verifiedAccessToken();
  if (!token) return "unauthorized";

  try {
    const response = await fetch(profileUrl(), {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(profile),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    if (response.status === 401) return "unauthorized";
    if (response.status === 422) return "invalid";
    return response.ok ? "ok" : "unavailable";
  } catch {
    return "unavailable";
  }
}
