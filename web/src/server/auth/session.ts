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
    const { data: userData, error: userError } = await supabase.auth.getUser();
    if (userError || !userData.user) return null;

    const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
    if (sessionError || !sessionData.session) return null;
    if (sessionData.session.user.id !== userData.user.id) return null;
    return sessionData.session.access_token;
  } catch {
    return null;
  }
}
