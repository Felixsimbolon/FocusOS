import { createClient } from "../../lib/supabase/server";

export type ServerUser = {
  id: string;
  email: string | null;
};

/** Return only identity fields after Supabase verifies the current session. */
export async function getServerUser(): Promise<ServerUser | null> {
  try {
    const supabase = await createClient();
    const { data, error } = await supabase.auth.getUser();

    if (error || !data.user) {
      return null;
    }

    return {
      id: data.user.id,
      email: data.user.email ?? null,
    };
  } catch {
    return null;
  }
}


/** Return the verified user's current Supabase access token for a server-to-server API call. */
export async function getServerAccessToken(): Promise<string | null> {
  try {
    const supabase = await createClient();
    const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
    const token = sessionData.session?.access_token;
    if (sessionError || !token) return null;

    // Verify the exact token forwarded to FastAPI. The tokens-only cookie
    // need not carry a full or current session.user object.
    const { data: userData, error: userError } = await supabase.auth.getUser(token);
    if (userError || !userData.user) return null;
    return token;
  } catch {
    return null;
  }
}
