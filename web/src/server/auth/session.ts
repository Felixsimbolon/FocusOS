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
