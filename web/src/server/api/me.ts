import "server-only";

import { getServerUser, type ServerUser } from "../auth/session";
import { readProfile, type WorkingHours } from "./profile";

export type Me = {
  user: ServerUser;
  profile: {
    timezone: string;
    working_hours: WorkingHours;
  } | null;
};

export type MeResult =
  | { kind: "ok"; data: Me }
  | { kind: "unauthorized" }
  | { kind: "unavailable"; user: ServerUser };

export async function getMe(): Promise<MeResult> {
  const user = await getServerUser();
  if (!user) return { kind: "unauthorized" };

  const result = await readProfile();
  if (result.kind === "unauthorized") return { kind: "unauthorized" };
  if (result.kind === "unavailable") return { kind: "unavailable", user };

  if (result.profile && result.profile.id !== user.id) {
    return { kind: "unavailable", user };
  }

  return {
    kind: "ok",
    data: {
      user: { id: user.id, email: user.email },
      profile: result.profile
        ? {
            timezone: result.profile.timezone,
            working_hours: {
              days: result.profile.working_hours.days,
              start_minute: result.profile.working_hours.start_minute,
              end_minute: result.profile.working_hours.end_minute,
            },
          }
        : null,
    },
  };
}
